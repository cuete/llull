"""Analysis service — the general map (level 0) and zoom into its nodes.

The general map is built from a sample of every section of a source rather than from
the whole text. Each node records which part of the text it stands for, so a zoom reads
only that part, and relationships are revised as more of the text is read.
"""
from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator

import numpy as np
import structlog
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentBlock
from app.models.graph import Edge, Node, NodeChunk
from app.models.source import Chunk, Source
from app.services.embeddings import EmbeddingService
from app.services.llm.base import LLMAdapter
from app.services.prompt import LLULL_SYSTEM_PROMPT
from app.services.sampling import (
    SectionInput,
    build_section_packets,
    pick_diverse,
    render_packets,
)
from app.services.sections import ensure_sections, is_low_information

log = structlog.get_logger()

CHARS_PER_TOKEN = 4
# Sources up to this size are read whole for the general map; larger ones are sampled
L0_FULL_READ_TOKENS = 15_000
L0_SAMPLE_SHARE = 0.25
L0_SAMPLE_MAX_TOKENS = 60_000
# A zoom reads a node's whole text up to this size, and a sample of it beyond
ZOOM_READ_TOKENS = 24_000
# Other map nodes listed in a zoom prompt
ZOOM_MAP_NODES = 80
# Links inferred from a sample are provisional
SAMPLED_CONFIDENCE_CAP = 0.6
# A run of this many consecutive passages that fit no node is a region the map missed
UNCOVERED_RUN = 3
SUGGEST_SAME_CONCEPT = 0.85
SUGGEST_SIMILAR = 0.6

# Language code → human-readable name for LLM prompts
_LANGUAGE_NAMES: dict[str, str] = {
    "es": "Spanish",
    "en": "English",
    "fr": "French",
    "de": "German",
    "pt": "Portuguese",
    "it": "Italian",
    "nl": "Dutch",
    "ru": "Russian",
    "zh-cn": "Chinese",
    "ja": "Japanese",
    "ar": "Arabic",
}


_EDGE_TYPE_MAP: dict[str, str] = {
    "relacional": "relational",
    "relational": "relational",
    "jerárquico": "hierarchical",
    "jerarquico": "hierarchical",
    "hierarchical": "hierarchical",
    "jerárquica": "hierarchical",
    "jerarquica": "hierarchical",
    "causal": "causal",
    "causale": "causal",
}


def _normalize_edge_type(t: str) -> str:
    return _EDGE_TYPE_MAP.get(str(t).lower().strip(), "relational")


def detect_language(text: str) -> str:
    """Detect the language of text. Returns ISO 639-1 code. Defaults to 'es' on failure."""
    try:
        from langdetect import detect
        return detect(text[:3000])
    except Exception:
        return "es"  # default to Spanish per project rules


def language_name_for(lang_code: str) -> str:
    """Return the human-readable language name for use in LLM prompts."""
    return _LANGUAGE_NAMES.get(lang_code, "Spanish")


_NODE_RULES = """What to INCLUDE as nodes:
- Abstract concepts and ideas central to the document's argument
- Themes and topics the document is fundamentally *about*
- Processes, principles, values, and problems discussed

What to EXCLUDE from nodes:
- Dates, proper names of people, publishers or source institutions
- URLs, citations, footnotes, bibliographic references, document metadata
- Two nodes that are synonyms or rewordings of the same idea — merge them"""

L0_MAP_PROMPT = """Build the GENERAL MAP of a document: its main ideas and how they relate.

IMPORTANT: Respond ENTIRELY in {language_name}. All node labels and descriptions must be in {language_name}.

{reading_note}

Return a JSON object with this exact structure:
{{
  "nodes": [
    {{
      "label": "short concept name (1-5 words)",
      "description": "the idea in 1-2 sentences",
      "sections": ["S1", "S4"]
    }}
  ],
  "edges": [
    {{
      "from_label": "label of source node",
      "to_label": "label of target node",
      "type": "relational|hierarchical|causal",
      "weight": 0.7,
      "confidence": 0.5,
      "evidence": "the passage or reason this link rests on, in a few words"
    }}
  ]
}}

Guidelines:
- This is the top layer only: {node_range} nodes for the whole document. Detail belongs to later zooms into a node, not here.
- "sections" lists every section (S1, S2, ...) where the idea is developed.
- EVERY section must appear in the "sections" of at least one node. Do not leave a section out.
- Only create edges between nodes in your list. Weight: strength of the relationship (0-1). Confidence: how sure you are given what you were shown (0-1).

{node_rules}

Return ONLY the raw JSON object. Start your response with {{ and end with }}.

Document sections:

{sections_text}"""

_READING_NOTE_SAMPLED = (
    "You are NOT shown the whole document. For each section you get its title, the terms "
    "distinctive to it (computed from the full section), and a selection of its passages. "
    "Base the map only on what is shown; links you infer are provisional and will be "
    "revised when the full text of a node is read."
)
_READING_NOTE_FULL = "You are shown the complete text of each section."

L0_REPAIR_PROMPT = """A general map was built for a document, but the passages below fit none of its nodes.

IMPORTANT: Respond ENTIRELY in {language_name}.

Existing nodes:
{nodes_list}

Passages not covered by the map:

{passages}

If these passages develop ideas missing from the map, return up to {max_nodes} additional nodes. If they only repeat existing nodes or carry no ideas, return an empty list.

Return ONLY a JSON object: {{"nodes": [{{"label": "...", "description": "..."}}]}}"""

DOC_GENERATION_PROMPT = """Based on the following knowledge graph extracted from a document, write a structured markdown summary.

IMPORTANT: Write ENTIRELY in {language_name}. Do not translate or use English.

Nodes (concepts):
{nodes_text}

Edges (relationships):
{edges_text}

Write 3-5 markdown paragraphs that synthesize these concepts into a coherent narrative. Use headers (##) for major themes. Be concise and factual."""

ZOOM_PROMPT = """Zoom into one concept of a knowledge map: identify its sub-concepts from the part of the document it stands for, and revise how it connects to the rest of the map.

IMPORTANT: Respond ENTIRELY in {language_name}. All labels and descriptions must be in {language_name}.

Concept being zoomed:
- Label: {label}
- Description: {description}

{reading_note}

Text of this concept:
---
{context}
---

Other nodes already on the map:
{map_nodes}

Existing links of the zoomed concept:
{existing_links}

Return a JSON object:
{{
  "nodes": [
    {{"label": "sub-concept label", "description": "the idea in 1-2 sentences"}}
  ],
  "edges": [
    {{
      "from_label": "a sub-concept",
      "to_label": "another sub-concept, or a node already on the map",
      "type": "relational|hierarchical|causal",
      "weight": 0.7,
      "confidence": 0.8,
      "evidence": "the passage this link rests on, in a few words"
    }}
  ],
  "link_reviews": [
    {{
      "other_label": "the node at the other end of an existing link",
      "verdict": "confirmed|weakened|unsupported",
      "evidence": "what in the text supports the verdict, in a few words"
    }}
  ]
}}

Guidelines:
- Generate 3-7 sub-concepts: the next layer only, not a full breakdown.
- Do NOT create a sub-concept that is the same idea as a node already on the map; add an edge to that node instead.
- "edges": links among the sub-concepts, and from a sub-concept to a node already on the map when the text shows the connection. The links from the zoomed concept to its sub-concepts are created automatically; do not list them.
- "link_reviews": one entry per existing link of the zoomed concept, judged against the text above. "confirmed" if the text backs it, "weakened" if only loosely, "unsupported" if the text gives no basis for it.
- Use only the text above. Do not use outside knowledge.

{node_rules}

Return ONLY the raw JSON object. Start your response with {{ and end with }}."""

_ZOOM_NOTE_FULL = "You are shown the complete text of the part of the document this concept stands for."
_ZOOM_NOTE_SAMPLED = (
    "This concept covers more text than can be read at once; you are shown a selection of "
    "its passages. Deeper zooms will read each part in full."
)


def _tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN + 1


def _norm_label(label: str) -> str:
    return " ".join(str(label).lower().split())


def _unit(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.where(norms == 0, 1.0, norms)


def _clamp(value: object, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _node_text(label: str, description: str) -> str:
    return f"{label}: {description}" if description else label


def assign_chunks_to_nodes(
    chunk_embeddings: list[list[float] | None],
    node_embeddings: list[list[float] | None],
    candidates: list[list[int]],
) -> tuple[list[int], list[float]]:
    """
    Give every chunk to one node, so no part of the text is left unreachable.

    candidates[i] lists the node indexes chunk i may go to (empty = any node). Returns,
    per chunk, the chosen node index and its similarity to that node (0 when unknown).
    """
    node_count = len(node_embeddings)
    usable = all(e is not None for e in node_embeddings) and node_count > 0
    node_matrix = _unit(np.array(node_embeddings, dtype=np.float32)) if usable else None

    chosen: list[int] = []
    similarity: list[float] = []
    for index, embedding in enumerate(chunk_embeddings):
        options = candidates[index] or list(range(node_count))
        if node_matrix is None or embedding is None:
            # No embeddings: spread chunks over their candidates in order
            chosen.append(options[index % len(options)])
            similarity.append(0.0)
            continue
        vector = np.array(embedding, dtype=np.float32)
        vector /= np.linalg.norm(vector) or 1.0
        scores = node_matrix[options] @ vector
        best = int(np.argmax(scores))
        chosen.append(options[best])
        similarity.append(float(scores[best]))
    return chosen, similarity


def uncovered_runs(similarity: list[float], run: int = UNCOVERED_RUN) -> list[int]:
    """Indexes of chunks in runs of consecutive poor fits: regions the map missed."""
    if len(similarity) < run * 2 or not any(similarity):
        return []
    values = np.array(similarity)
    threshold = float(values.mean() - 1.5 * values.std())
    low = values < threshold
    result: list[int] = []
    start = None
    for i, flag in enumerate(list(low) + [False]):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            if i - start >= run:
                result.extend(range(start, i))
            start = None
    return result


class AnalysisService:
    """Builds the general map of a source and zooms into its nodes."""

    def __init__(
        self,
        db: AsyncSession,
        llm: LLMAdapter,
        embeddings: EmbeddingService | None = None,
        l0_full_read_tokens: int = L0_FULL_READ_TOKENS,
        l0_sample_share: float = L0_SAMPLE_SHARE,
        l0_sample_max_tokens: int = L0_SAMPLE_MAX_TOKENS,
        zoom_read_tokens: int = ZOOM_READ_TOKENS,
    ) -> None:
        self._db = db
        self._llm = llm
        self._embeddings = embeddings
        self._l0_full_read_tokens = l0_full_read_tokens
        self._l0_sample_share = l0_sample_share
        self._l0_sample_max_tokens = l0_sample_max_tokens
        self._zoom_read_tokens = zoom_read_tokens

    # ── shared helpers ───────────────────────────────────────────────────────

    async def _complete(self, messages: list[dict]) -> str:
        response = ""
        async for token in await self._llm.complete(messages, stream=False):
            response += token
        return response

    async def _embed(self, texts: list[str]) -> list[list[float] | None]:
        if self._embeddings is None or not texts:
            return [None] * len(texts)
        try:
            return list(await self._embeddings.embed(texts))
        except Exception as e:
            # Degraded mode: the map still works, chunks are shared out without ranking
            log.warning("node_embedding_failed", error=str(e))
            return [None] * len(texts)

    def _chunk_embedding(self, chunk: Chunk) -> list[float] | None:
        return json.loads(chunk.embedding_json) if chunk.embedding_json else None

    async def _ensure_chunks(self, source: Source) -> None:
        """Chunk (and embed) a source that was stored without chunks."""
        existing = await self._db.execute(
            select(Chunk.id).where(Chunk.source_id == source.id).limit(1)
        )
        if existing.scalar_one_or_none() is not None or not source.extracted_text.strip():
            return
        from app.services.ingest import chunk_text

        texts = chunk_text(source.extracted_text)
        embeddings = await self._embed(texts)
        for order, (text, embedding) in enumerate(zip(texts, embeddings)):
            self._db.add(
                Chunk(
                    id=str(uuid.uuid4()),
                    source_id=source.id,
                    topic_id=source.topic_id,
                    text=text,
                    order=order,
                    embedding_json=json.dumps(embedding) if embedding is not None else None,
                )
            )
        await self._db.flush()

    async def _delete_source_graph(self, source_id: str) -> None:
        """Remove a source's nodes, their links and text assignments (for re-analysis)."""
        node_ids = select(Node.id).where(Node.source_id == source_id)
        await self._db.execute(
            delete(Edge).where(or_(Edge.from_node_id.in_(node_ids), Edge.to_node_id.in_(node_ids)))
        )
        await self._db.execute(delete(NodeChunk).where(NodeChunk.node_id.in_(node_ids)))
        await self._db.execute(delete(Node).where(Node.source_id == source_id))
        await self._db.flush()

    # ── level 0: the general map ─────────────────────────────────────────────

    async def analyze_l0(
        self, topic_id: str, source: Source
    ) -> AsyncGenerator[tuple[str, dict], None]:
        """
        Build the general map of a source.

        Short sources are read whole. Longer ones are sampled: every section contributes
        its title, distinctive terms and a selection of passages, in a single LLM call.
        Every content chunk is then assigned to a node, so zooms can read exactly the
        part of the text a node stands for.

        Yields (event_type, data) tuples for SSE streaming.
        """
        yield "progress", {"step": "preparing", "pct": 5}

        lang_name = language_name_for(detect_language(source.extracted_text))

        await self._ensure_chunks(source)
        sections, chunks = await ensure_sections(self._db, source)
        if not chunks:
            yield "error", {"code": "EMPTY_SOURCE", "message": "The source has no text to analyze"}
            return

        position = {chunk.id: i for i, chunk in enumerate(chunks)}
        content_sections = [s for s in sections if not s.is_boilerplate] or sections
        section_inputs: list[SectionInput] = []
        for section in content_sections:
            positions = [position[c.id] for c in chunks if c.section_id == section.id]
            if positions:
                section_inputs.append(SectionInput(title=section.title, chunk_positions=positions))

        chunk_texts = [c.text for c in chunks]
        chunk_embeddings = [self._chunk_embedding(c) for c in chunks]
        content_positions = [
            p
            for s in section_inputs
            for p in s.chunk_positions
            if not is_low_information(chunk_texts[p])
        ] or [p for s in section_inputs for p in s.chunk_positions]
        content_tokens = sum(_tokens(chunk_texts[p]) for p in content_positions)

        sampled = content_tokens > self._l0_full_read_tokens
        if sampled:
            budget = min(
                self._l0_sample_max_tokens,
                max(self._l0_full_read_tokens, int(content_tokens * self._l0_sample_share)),
            )
            packets = build_section_packets(section_inputs, chunk_texts, chunk_embeddings, budget)
            sections_text = render_packets(packets)
        else:
            sections_text = "\n\n".join(
                f"## S{i + 1} — {s.title or 'Untitled section'}\n"
                + "\n".join(chunk_texts[p] for p in s.chunk_positions)
                for i, s in enumerate(section_inputs)
            )
        log.info(
            "l0_reading",
            source_id=source.id,
            sections=len(section_inputs),
            content_tokens=content_tokens,
            read_tokens=_tokens(sections_text),
            sampled=sampled,
        )
        yield "progress", {
            "step": f"reading_{len(section_inputs)}_sections",
            "pct": 15,
            "sampled": sampled,
            "read_tokens": _tokens(sections_text),
            "content_tokens": content_tokens,
        }

        prompt = L0_MAP_PROMPT.format(
            language_name=lang_name,
            reading_note=_READING_NOTE_SAMPLED if sampled else _READING_NOTE_FULL,
            node_range="6-20" if len(section_inputs) > 3 else "3-10",
            node_rules=_NODE_RULES,
            sections_text=sections_text,
        )
        response = await self._complete(
            [
                {"role": "system", "content": LLULL_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
        )
        graph_data = self._extract_json(response)
        if not isinstance(graph_data, dict) or not graph_data.get("nodes"):
            yield "error", {"code": "PARSE_FAILED", "message": "LLM returned no usable map"}
            return

        yield "progress", {"step": "assigning_text_to_nodes", "pct": 60}

        # Re-analysis replaces the source's previous map; only once a new one is in hand
        await self._delete_source_graph(source.id)

        basis = "sampled" if sampled else "read"
        nodes: list[Node] = []
        node_sections: list[set[int]] = []
        seen_labels: set[str] = set()
        for node_data in graph_data.get("nodes", []):
            label = str(node_data.get("label", "")).strip()
            if not label or _norm_label(label) in seen_labels:
                continue
            seen_labels.add(_norm_label(label))
            node = Node(
                id=str(uuid.uuid4()),
                topic_id=topic_id,
                source_id=source.id,
                label=label[:500],
                description=str(node_data.get("description", "")),
                status="unexplored",
                level=0,
            )
            self._db.add(node)
            nodes.append(node)
            node_sections.append(
                {
                    int(str(ref).strip().lstrip("Ss")) - 1
                    for ref in node_data.get("sections", []) or []
                    if str(ref).strip().lstrip("Ss").isdigit()
                }
            )

        node_embeddings = await self._embed([_node_text(n.label, n.description) for n in nodes])
        for node, embedding in zip(nodes, node_embeddings):
            node.embedding_json = json.dumps(embedding) if embedding is not None else None

        section_of = {p: i for i, s in enumerate(section_inputs) for p in s.chunk_positions}
        candidates = [
            [n for n, refs in enumerate(node_sections) if section_of[p] in refs]
            for p in content_positions
        ]
        assigned, similarity = assign_chunks_to_nodes(
            [chunk_embeddings[p] for p in content_positions], node_embeddings, candidates
        )

        # Coverage repair: a region that fits no node gets a second, small look
        uncovered = uncovered_runs(similarity)
        if uncovered:
            yield "progress", {"step": "checking_coverage", "pct": 70}
            new_nodes = await self._repair_coverage(
                topic_id,
                source,
                nodes,
                [chunk_texts[content_positions[i]] for i in uncovered],
                [chunk_embeddings[content_positions[i]] for i in uncovered],
                lang_name,
            )
            if new_nodes:
                new_embeddings = await self._embed(
                    [_node_text(n.label, n.description) for n in new_nodes]
                )
                for node, embedding in zip(new_nodes, new_embeddings):
                    node.embedding_json = json.dumps(embedding) if embedding is not None else None
                first_new = len(nodes)
                nodes.extend(new_nodes)
                node_embeddings.extend(new_embeddings)
                new_indexes = list(range(first_new, len(nodes)))
                # The missed regions may go to their previous node or to a new one
                for i in uncovered:
                    candidates[i] = sorted({assigned[i], *new_indexes})
                assigned, similarity = assign_chunks_to_nodes(
                    [chunk_embeddings[p] for p in content_positions], node_embeddings, candidates
                )

        await self._db.flush()
        for chunk_index, node_index in enumerate(assigned):
            self._db.add(
                NodeChunk(node_id=nodes[node_index].id, chunk_id=chunks[content_positions[chunk_index]].id)
            )
        for index, node in enumerate(nodes):
            node.coverage = round(assigned.count(index) / len(assigned), 4) if assigned else None

        yield "progress", {"step": "persisting", "pct": 80}

        nodes_by_label = {_norm_label(n.label): n for n in nodes}
        new_edges: list[Edge] = []
        seen_pairs: set[tuple[str, str]] = set()
        for edge_data in graph_data.get("edges", []):
            from_node = nodes_by_label.get(_norm_label(edge_data.get("from_label", "")))
            to_node = nodes_by_label.get(_norm_label(edge_data.get("to_label", "")))
            if not from_node or not to_node or from_node.id == to_node.id:
                continue
            pair = tuple(sorted((from_node.id, to_node.id)))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            confidence = _clamp(edge_data.get("confidence"), 0.5)
            edge = Edge(
                id=str(uuid.uuid4()),
                from_node_id=from_node.id,
                to_node_id=to_node.id,
                type=_normalize_edge_type(edge_data.get("type", "relational")),
                weight=_clamp(edge_data.get("weight"), 0.5),
                confidence=min(confidence, SAMPLED_CONFIDENCE_CAP) if sampled else confidence,
                basis=basis,
                evidence=str(edge_data.get("evidence") or "")[:500] or None,
            )
            self._db.add(edge)
            new_edges.append(edge)

        await self._db.flush()

        yield "nodes_updated", {
            "new_nodes": [{"id": n.id, "label": n.label} for n in nodes],
            "new_edges": [{"id": e.id} for e in new_edges],
        }

        # Generate document blocks from the extracted graph
        yield "progress", {"step": "generating_document", "pct": 85}
        doc_block_count = await self._generate_document_blocks(
            topic_id=topic_id,
            source=source,
            nodes=nodes,
            edges=new_edges,
            language_name=lang_name,
        )
        yield "document_updated", {"blocks": doc_block_count}

        yield "done", {
            "source_id": source.id,
            "nodes": len(nodes),
            "edges": len(new_edges),
            "sampled": sampled,
            "read_tokens": _tokens(sections_text),
            "content_tokens": content_tokens,
        }

    async def _repair_coverage(
        self,
        topic_id: str,
        source: Source,
        nodes: list[Node],
        texts: list[str],
        embeddings: list[list[float] | None],
        lang_name: str,
        max_passages: int = 8,
        max_nodes: int = 4,
    ) -> list[Node]:
        """Ask for the nodes missing from the map, given passages that fit none of them."""
        try:
            if all(e is not None for e in embeddings) and len(texts) > max_passages:
                picked = pick_diverse(np.array(embeddings, dtype=np.float32), max_passages)
            else:
                picked = list(range(min(len(texts), max_passages)))
            prompt = L0_REPAIR_PROMPT.format(
                language_name=lang_name,
                nodes_list="\n".join(f"- {_node_text(n.label, n.description)}" for n in nodes),
                passages="\n\n---\n\n".join(texts[i] for i in picked),
                max_nodes=max_nodes,
            )
            data = self._extract_json(await self._complete([{"role": "user", "content": prompt}]))
        except Exception as e:
            log.warning("coverage_repair_failed", error=str(e))
            return []

        existing = {_norm_label(n.label) for n in nodes}
        new_nodes: list[Node] = []
        for node_data in (data or {}).get("nodes", [])[:max_nodes]:
            label = str(node_data.get("label", "")).strip()
            if not label or _norm_label(label) in existing:
                continue
            existing.add(_norm_label(label))
            node = Node(
                id=str(uuid.uuid4()),
                topic_id=topic_id,
                source_id=source.id,
                label=label[:500],
                description=str(node_data.get("description", "")),
                status="unexplored",
                level=0,
            )
            self._db.add(node)
            new_nodes.append(node)
        log.info("coverage_repair", uncovered_passages=len(texts), new_nodes=len(new_nodes))
        return new_nodes

    async def _generate_document_blocks(
        self,
        topic_id: str,
        source: Source,
        nodes: list[Node],
        edges: list[Edge],
        language_name: str = "Spanish",
    ) -> int:
        """Generate document blocks summarizing the extracted knowledge graph.

        Fetches or creates the Document for the topic, calls the LLM to produce
        a markdown narrative, and persists one DocumentBlock per paragraph.
        Returns the number of blocks created.
        """
        # Fetch or create the Document record for this topic
        doc_result = await self._db.execute(
            select(Document).where(Document.topic_id == topic_id)
        )
        doc = doc_result.scalar_one_or_none()
        if doc is None:
            doc = Document(id=str(uuid.uuid4()), topic_id=topic_id)
            self._db.add(doc)
            await self._db.flush()

        # Delete any existing blocks for this source so re-analysis is clean
        existing_result = await self._db.execute(
            select(DocumentBlock).where(
                DocumentBlock.document_id == doc.id,
                DocumentBlock.source_id == source.id,
            )
        )
        for old_block in existing_result.scalars().all():
            await self._db.delete(old_block)
        await self._db.flush()

        # Build text representations of the graph
        nodes_text = "\n".join(
            f"- {n.label}: {n.description}" for n in nodes
        )
        # Use labels instead of IDs for readability
        node_id_to_label = {n.id: n.label for n in nodes}
        edges_text = "\n".join(
            f"- {node_id_to_label.get(e.from_node_id, e.from_node_id)}"
            f" --[{e.type}]--> "
            f"{node_id_to_label.get(e.to_node_id, e.to_node_id)}"
            for e in edges
        )

        prompt_content = DOC_GENERATION_PROMPT.format(
            language_name=language_name,
            nodes_text=nodes_text,
            edges_text=edges_text,
        )
        response_text = await self._complete(
            [
                {"role": "system", "content": LLULL_SYSTEM_PROMPT},
                {"role": "user", "content": prompt_content},
            ]
        )

        # Split into paragraphs and persist as blocks
        raw_blocks = [b.strip() for b in response_text.split("\n\n") if b.strip()]
        if not raw_blocks:
            raw_blocks = [response_text.strip()]

        # Get max existing order to avoid conflicts with other sources
        order_result = await self._db.execute(
            select(DocumentBlock.order)
            .where(DocumentBlock.document_id == doc.id)
            .order_by(DocumentBlock.order.desc())
            .limit(1)
        )
        base_order = (order_result.scalar_one_or_none() or -1) + 1

        for i, block_content in enumerate(raw_blocks):
            block = DocumentBlock(
                id=str(uuid.uuid4()),
                document_id=doc.id,
                source_id=source.id,
                content_md=block_content,
                order=base_order + i,
            )
            self._db.add(block)

        await self._db.flush()
        log.info("document_blocks_created", count=len(raw_blocks), topic_id=topic_id)
        return len(raw_blocks)

    # ── zoom ─────────────────────────────────────────────────────────────────

    async def _node_chunks(self, node: Node) -> tuple[list[Chunk], bool]:
        """
        The chunks a node stands for, in source order, and whether they are its own.

        Nodes created before text assignment existed have none; for those, the passages
        most similar to the node are used instead.
        """
        result = await self._db.execute(
            select(Chunk)
            .join(NodeChunk, NodeChunk.chunk_id == Chunk.id)
            .where(NodeChunk.node_id == node.id)
            .order_by(Chunk.order)
        )
        own = list(result.scalars().all())
        if own:
            return own, True

        result = await self._db.execute(
            select(Chunk).where(Chunk.source_id == node.source_id).order_by(Chunk.order)
        )
        candidates = [c for c in result.scalars().all() if not is_low_information(c.text)]
        if not candidates:
            return [], False
        limit = max(1, (self._zoom_read_tokens // 2) // max(1, _tokens(candidates[0].text)))
        node_embedding = (await self._embed([_node_text(node.label, node.description)]))[0]
        embeddings = [self._chunk_embedding(c) for c in candidates]
        if node_embedding is None or any(e is None for e in embeddings):
            return candidates[:limit], False
        scores = _unit(np.array(embeddings, dtype=np.float32)) @ (
            np.array(node_embedding, dtype=np.float32) / (np.linalg.norm(node_embedding) or 1.0)
        )
        top = sorted(np.argsort(scores)[::-1][:limit].tolist())
        return [candidates[i] for i in top], False

    async def zoom(
        self, topic_id: str, node: Node
    ) -> AsyncGenerator[tuple[str, dict], None]:
        """
        Zoom into a node: read the part of the text it stands for, create its
        sub-nodes, and revise the node's links with what the text shows.

        Yields (event_type, data) tuples for SSE streaming.
        """
        yield "progress", {"step": "zooming", "pct": 10}

        source_result = await self._db.execute(select(Source).where(Source.id == node.source_id))
        source = source_result.scalar_one_or_none()
        lang_name = (
            language_name_for(detect_language(source.extracted_text))
            if source and source.extracted_text
            else "Spanish"
        )

        node_chunks, owns_chunks = await self._node_chunks(node)
        read_chunks = node_chunks
        fully_read = owns_chunks
        if sum(_tokens(c.text) for c in node_chunks) > self._zoom_read_tokens:
            fully_read = False
            keep = max(1, self._zoom_read_tokens // max(1, _tokens(node_chunks[0].text)))
            embeddings = [self._chunk_embedding(c) for c in node_chunks]
            if all(e is not None for e in embeddings):
                picked = pick_diverse(np.array(embeddings, dtype=np.float32), keep)
            else:
                step = max(1, len(node_chunks) // keep)
                picked = list(range(0, len(node_chunks), step))[:keep]
            read_chunks = [node_chunks[i] for i in picked]
        basis = "read" if fully_read else "sampled"

        nodes_result = await self._db.execute(
            select(Node).where(Node.topic_id == topic_id).order_by(Node.level, Node.created_at)
        )
        all_nodes = list(nodes_result.scalars().all())
        nodes_by_id = {n.id: n for n in all_nodes}
        other_nodes = [n for n in all_nodes if n.id != node.id and n.parent_id != node.id]

        edges_result = await self._db.execute(
            select(Edge).where(or_(Edge.from_node_id == node.id, Edge.to_node_id == node.id))
        )
        node_edges = [
            e
            for e in edges_result.scalars().all()
            if (e.to_node_id if e.from_node_id == node.id else e.from_node_id) in nodes_by_id
        ]

        def _other_end(edge: Edge) -> Node:
            return nodes_by_id[edge.to_node_id if edge.from_node_id == node.id else edge.from_node_id]

        reviewable = [e for e in node_edges if _other_end(e).parent_id != node.id]
        prompt = ZOOM_PROMPT.format(
            language_name=lang_name,
            label=node.label,
            description=node.description,
            reading_note=_ZOOM_NOTE_FULL if fully_read else _ZOOM_NOTE_SAMPLED,
            context="\n\n".join(c.text for c in read_chunks),
            map_nodes="\n".join(
                f"- {_node_text(n.label, n.description[:160])}" for n in other_nodes[:ZOOM_MAP_NODES]
            )
            or "(none)",
            existing_links="\n".join(
                f"- {node.label} —[{e.type}, {e.basis}]— {_other_end(e).label}" for e in reviewable
            )
            or "(none)",
            node_rules=_NODE_RULES,
        )

        response_text = await self._complete(
            [
                {"role": "system", "content": LLULL_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
        )

        yield "progress", {"step": "parsing_zoom", "pct": 60}

        graph_data = self._extract_json(response_text)
        if not isinstance(graph_data, dict):
            yield "error", {"code": "PARSE_FAILED", "message": "LLM returned invalid JSON for zoom"}
            return

        node.status = "zoomed"

        existing_labels = {_norm_label(n.label): n for n in all_nodes}
        sub_nodes: list[Node] = []
        for node_data in graph_data.get("nodes", []):
            label = str(node_data.get("label", "")).strip()
            # A sub-concept that already exists on the map is linked, not duplicated
            if not label or _norm_label(label) in existing_labels:
                continue
            sub_node = Node(
                id=str(uuid.uuid4()),
                topic_id=topic_id,
                source_id=node.source_id,
                label=label[:500],
                description=str(node_data.get("description", "")),
                status="unexplored",
                level=node.level + 1,
                parent_id=node.id,
            )
            self._db.add(sub_node)
            sub_nodes.append(sub_node)
            existing_labels[_norm_label(label)] = sub_node

        sub_embeddings = await self._embed([_node_text(n.label, n.description) for n in sub_nodes])
        for sub_node, embedding in zip(sub_nodes, sub_embeddings):
            sub_node.embedding_json = json.dumps(embedding) if embedding is not None else None
        await self._db.flush()

        # Every chunk of the parent goes to one sub-node, so nothing becomes unreachable
        if sub_nodes and owns_chunks:
            assigned, _ = assign_chunks_to_nodes(
                [self._chunk_embedding(c) for c in node_chunks],
                sub_embeddings,
                [[] for _ in node_chunks],
            )
            for chunk, sub_index in zip(node_chunks, assigned):
                self._db.add(NodeChunk(node_id=sub_nodes[sub_index].id, chunk_id=chunk.id))
            for index, sub_node in enumerate(sub_nodes):
                if node.coverage is not None:
                    sub_node.coverage = round(
                        node.coverage * assigned.count(index) / len(node_chunks), 4
                    )

        new_edges: list[Edge] = []
        for sub_node in sub_nodes:
            edge = Edge(
                id=str(uuid.uuid4()),
                from_node_id=node.id,
                to_node_id=sub_node.id,
                type="hierarchical",
                weight=0.8,
                confidence=0.9,
                basis=basis,
            )
            self._db.add(edge)
            new_edges.append(edge)

        topic_edges_result = await self._db.execute(
            select(Edge).where(
                Edge.from_node_id.in_(select(Node.id).where(Node.topic_id == topic_id))
            )
        )
        edges_by_pair: dict[tuple[str, str], Edge] = {
            tuple(sorted((e.from_node_id, e.to_node_id))): e
            for e in topic_edges_result.scalars().all()
        }
        for edge in new_edges:
            edges_by_pair[tuple(sorted((edge.from_node_id, edge.to_node_id)))] = edge
        revised = 0

        grounding = {"suggested": 0, "sampled": 1, "read": 2}

        def _link(
            a: Node, b: Node, edge_type: str, weight: float, confidence: float, evidence: str | None
        ) -> str | None:
            """Create the link a—b, or upgrade it if this reading grounds it better."""
            pair = tuple(sorted((a.id, b.id)))
            existing = edges_by_pair.get(pair)
            if existing is None:
                edge = Edge(
                    id=str(uuid.uuid4()),
                    from_node_id=a.id,
                    to_node_id=b.id,
                    type=edge_type,
                    weight=weight,
                    confidence=confidence,
                    basis=basis,
                    evidence=evidence,
                )
                self._db.add(edge)
                edges_by_pair[pair] = edge
                new_edges.append(edge)
                return "created"
            better_grounded = grounding.get(basis, 0) > grounding.get(existing.basis, 0)
            if better_grounded or existing.status != "active":
                existing.basis = basis if better_grounded else existing.basis
                existing.status = "active"
                existing.confidence = max(existing.confidence, confidence)
                existing.evidence = evidence or existing.evidence
                return "updated"
            return None

        def _ancestor_at(target: Node, level: int) -> Node:
            while target.level > level and target.parent_id in nodes_by_id:
                target = nodes_by_id[target.parent_id]
            return target

        sub_ids = {n.id for n in sub_nodes}
        for edge_data in graph_data.get("edges", []):
            a = existing_labels.get(_norm_label(edge_data.get("from_label", "")))
            b = existing_labels.get(_norm_label(edge_data.get("to_label", "")))
            if not a or not b or a.id == b.id:
                continue
            if {a.id, b.id} <= {node.id, *sub_ids} and node.id in (a.id, b.id):
                continue  # parent↔sub links are created above
            confidence = _clamp(edge_data.get("confidence"), 0.6)
            if not fully_read:
                confidence = min(confidence, SAMPLED_CONFIDENCE_CAP)
            evidence = str(edge_data.get("evidence") or "")[:500] or None
            outcome = _link(
                a,
                b,
                _normalize_edge_type(edge_data.get("type", "relational")),
                _clamp(edge_data.get("weight"), 0.6),
                confidence,
                evidence,
            )
            revised += outcome == "updated"
            # Roll the link up: a sub-concept tied to another part of the map ties its parent too
            inside, outside = (a, b) if a.id in sub_ids else (b, a)
            if inside.id in sub_ids and outside.id not in sub_ids and outside.id != node.id:
                target = _ancestor_at(outside, node.level)
                if target.id != node.id and target.parent_id != node.id:
                    rolled = _link(
                        node,
                        target,
                        "relational",
                        0.6,
                        round(confidence * 0.8, 4),
                        f"Via {inside.label} ↔ {outside.label}",
                    )
                    revised += rolled == "updated"

        # Verdicts on the node's existing links, judged against its text
        reviewable_by_label = {_norm_label(_other_end(e).label): e for e in reviewable}
        for review in graph_data.get("link_reviews", []) or []:
            edge = reviewable_by_label.get(_norm_label(review.get("other_label", "")))
            if edge is None:
                continue
            verdict = str(review.get("verdict", "")).lower().strip()
            evidence = str(review.get("evidence") or "")[:500] or None
            if verdict == "confirmed":
                edge.basis = basis
                edge.status = "active"
                edge.confidence = max(edge.confidence, 0.8 if fully_read else SAMPLED_CONFIDENCE_CAP)
            elif verdict == "weakened":
                edge.basis = basis
                edge.confidence = round(edge.confidence * 0.6, 4)
            elif verdict == "unsupported":
                # One end's text cannot rule a link out; it takes both ends being read
                if fully_read and _other_end(edge).status == "zoomed":
                    edge.status = "unsupported"
                    edge.basis = "read"
                edge.confidence = round(edge.confidence * 0.5, 4)
            else:
                continue
            edge.evidence = evidence or edge.evidence
            revised += 1

        # Free suggestions: sub-concepts that closely resemble a node elsewhere on the map
        suggested = self._suggest_links(node, sub_nodes, sub_embeddings, other_nodes, edges_by_pair)
        new_edges.extend(suggested)

        await self._db.flush()

        yield "nodes_updated", {
            "new_nodes": [{"id": n.id, "label": n.label} for n in sub_nodes],
            "new_edges": [{"id": e.id} for e in new_edges],
        }
        yield "done", {
            "node_id": node.id,
            "sub_nodes": len(sub_nodes),
            "new_links": len(new_edges) - len(sub_nodes),
            "revised_links": int(revised),
            "read_tokens": sum(_tokens(c.text) for c in read_chunks),
            "fully_read": fully_read,
        }

    def _suggest_links(
        self,
        node: Node,
        sub_nodes: list[Node],
        sub_embeddings: list[list[float] | None],
        other_nodes: list[Node],
        edges_by_pair: dict[tuple[str, str], Edge],
    ) -> list[Edge]:
        """Possible links from embedding similarity alone — nothing is read for these."""
        candidates = [n for n in other_nodes if n.embedding_json and n.id != node.parent_id]
        if not candidates or not sub_nodes or any(e is None for e in sub_embeddings):
            return []
        matrix = _unit(np.array([json.loads(n.embedding_json) for n in candidates], dtype=np.float32))
        subs = _unit(np.array(sub_embeddings, dtype=np.float32))
        scores = subs @ matrix.T
        suggested: list[Edge] = []
        for index, sub_node in enumerate(sub_nodes):
            best = int(np.argmax(scores[index]))
            score = float(scores[index, best])
            target = candidates[best]
            pair = tuple(sorted((sub_node.id, target.id)))
            if score < SUGGEST_SIMILAR or pair in edges_by_pair:
                continue
            edge = Edge(
                id=str(uuid.uuid4()),
                from_node_id=sub_node.id,
                to_node_id=target.id,
                type="relational",
                weight=round(score, 4),
                confidence=0.2,
                basis="suggested",
                evidence=(
                    "Possibly the same concept" if score >= SUGGEST_SAME_CONCEPT else "Similar concept"
                ),
            )
            self._db.add(edge)
            edges_by_pair[pair] = edge
            suggested.append(edge)
        return suggested

    def _extract_json(self, text: str) -> dict | None:
        """Extract JSON from LLM response, handling markdown code blocks and partial JSON."""
        import re
        text = text.strip()

        def _parse_and_normalize(raw: str) -> dict | None:
            """Parse JSON and normalize keys (strip whitespace from keys)."""
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    # Normalize keys: strip leading/trailing whitespace and newlines
                    return {k.strip(): v for k, v in parsed.items()}
                return parsed
            except json.JSONDecodeError:
                return None

        # Try direct parse
        result = _parse_and_normalize(text)
        if result is not None:
            return result

        # Try markdown code blocks
        for pattern in [r"```json\s*([\s\S]*?)\s*```", r"```\s*([\s\S]*?)\s*```"]:
            match = re.search(pattern, text)
            if match:
                result = _parse_and_normalize(match.group(1))
                if result is not None:
                    return result

        # Find outermost { ... } (first { to last })
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            result = _parse_and_normalize(text[start:end + 1])
            if result is not None:
                return result

        # Last resort: LLM returned JSON content without outer braces
        if '"nodes"' in text or '"edges"' in text:
            result = _parse_and_normalize("{" + text.strip().strip(",") + "}")
            if result is not None:
                return result

        log.warning("json_extract_failed", response_preview=text[:300])
        return None
