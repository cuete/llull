"""Analysis service — level 0 graph extraction and zoom operations."""
from __future__ import annotations

import json
import re
import string
import uuid
from collections.abc import AsyncGenerator

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentBlock
from app.models.graph import Edge, Node
from app.models.source import Source
from app.services.llm.base import LLMAdapter
from app.services.prompt import LLULL_SYSTEM_PROMPT

log = structlog.get_logger()

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
    return _EDGE_TYPE_MAP.get(t.lower().strip(), "relational")


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


# L0 analysis prompt
L0_ANALYSIS_PROMPT = """Analyze the following document content and extract a knowledge graph.

IMPORTANT: Respond ENTIRELY in {language_name}. All node labels, descriptions, and edge types must be in {language_name}. Do not translate or use English.

Return a JSON object with this exact structure:
{{
  "nodes": [
    {{
      "label": "short concept name (1-5 words)",
      "description": "atomic idea in 1-2 sentences"
    }}
  ],
  "edges": [
    {{
      "from_label": "label of source node",
      "to_label": "label of target node",
      "type": "relational|hierarchical|causal",
      "weight": 0.7,
      "confidence": 0.8
    }}
  ]
}}

Guidelines:
- Extract 3-8 key concepts as nodes — prefer fewer, higher-quality nodes over exhaustive coverage
- Each node should represent one distinct, atomic idea not already captured by another node
- Identify meaningful relationships between nodes
- Weight: 0-1, strength of relationship
- Confidence: 0-1, how certain you are based on the text
- Only create edges between nodes in your list

CRITICAL — What to INCLUDE as nodes:
- Abstract concepts and ideas central to the document's argument
- Themes and topics the document is fundamentally *about*
- Processes, principles, values, and problems discussed
- Relationships between ideas expressed as concepts

CRITICAL — What to EXCLUDE from nodes (do NOT create nodes for these):
- Dates, times, years, or any temporal references (e.g. "May 25, 2026", "20th century")
- Proper names of people — authors, signatories, speakers, or any individual (e.g. "Pope Leo XIV", "John Smith")
- Organizations or institutions that are the *source or publisher* of the document, not the subject of its ideas (e.g. "Vatican Media", "Dicasterio para la Comunicación")
- URLs, citations, footnotes, or bibliographic references
- Geographic locations unless the location itself is the conceptual subject of the argument (e.g. exclude "Rome" as a dateline, include "Global South" if it is the topic)
- Document metadata: titles, bylines, issue numbers, page numbers

Deduplication — avoid semantic duplicates:
- If two candidate labels represent the same underlying concept, merge them into one node using the clearest label
- Do NOT emit two nodes that are synonyms, translations of each other, or slight rewordings of the same idea

Return ONLY the raw JSON object. Do not add any explanation, commentary, or markdown formatting. Start your response with {{ and end with }}.

Document content:
"""

DOC_GENERATION_PROMPT = """Based on the following knowledge graph extracted from a document, write a structured markdown summary.

IMPORTANT: Write ENTIRELY in {language_name}. Do not translate or use English.

Nodes (concepts):
{nodes_text}

Edges (relationships):
{edges_text}

Write 3-5 markdown paragraphs that synthesize these concepts into a coherent narrative. Use headers (##) for major themes. Be concise and factual."""

ZOOM_PROMPT = """Zoom into the following concept from a knowledge graph and generate sub-nodes that elaborate on its meaning.

IMPORTANT: Respond ENTIRELY in {language_name}. All sub-node labels and descriptions must be in {language_name}. Do not translate or use English.

Parent node:
- Label: {label}
- Description: {description}

Document context:
{context}

Return a JSON object:
{{
  "nodes": [
    {{
      "label": "sub-concept label",
      "description": "detailed atomic idea"
    }}
  ],
  "edges": [
    {{
      "from_label": "{label}",
      "to_label": "sub-concept label",
      "type": "hierarchical",
      "weight": 0.8,
      "confidence": 0.9
    }}
  ]
}}

Generate 3-7 sub-nodes that elaborate on the parent concept.

CRITICAL — What to INCLUDE as sub-nodes:
- Abstract sub-concepts, dimensions, or facets of the parent idea
- Principles, mechanisms, or implications of the parent concept as discussed in the document

CRITICAL — What to EXCLUDE from sub-nodes (do NOT create nodes for these):
- Dates, times, years, or any temporal references
- Proper names of individual people (authors, figures mentioned in passing)
- Organizations or institutions that are sources/publishers of the document, not conceptual subjects
- URLs, citations, or bibliographic references
- Geographic locations unless they are the conceptual focus

Deduplication: if two candidate sub-nodes represent the same idea, merge them into one with the clearest label."""


def split_into_sections(text: str, max_section_chars: int = 20000) -> list[str]:
    """
    Split document text into semantically coherent sections.

    Strategy (in order of precedence):
    1. Split on markdown headers: lines starting with #, ##, ###
    2. Split on common section patterns: "Capítulo N", "Chapter N", "Section N",
       "Artículo N", "Article N", roman numerals (I., II., III.) at line start
    3. Split on double newlines (paragraph boundaries) if section exceeds max_section_chars
    4. If a resulting section still exceeds max_section_chars, hard-split at paragraph boundary

    Returns list of non-empty section strings, each <= max_section_chars.
    Min sections: 1 (whole text if no boundaries found).
    """
    # Regex for structural boundaries at the start of a line
    _HEADER_RE = re.compile(
        r"^(?:"
        r"#{1,3}\s+"                         # Markdown headers: #, ##, ###
        r"|(?:Cap[ií]tulo|Chapter|Section|Sección|Artículo|Article)\s+[\w]+"  # Named sections
        r"|(?:I{1,3}|IV|VI{0,3}|IX|XI{0,3}|XIV|XV)\.\s"  # Roman numerals I.–XV.
        r")",
        re.MULTILINE | re.IGNORECASE,
    )

    def _sub_split(section: str) -> list[str]:
        """Split a single section that exceeds max_section_chars at paragraph boundaries."""
        if len(section) <= max_section_chars:
            return [section]
        parts: list[str] = []
        paragraphs = re.split(r"\n{2,}", section)
        current = ""
        for para in paragraphs:
            candidate = (current + "\n\n" + para).lstrip("\n") if current else para
            if len(candidate) > max_section_chars and current:
                parts.append(current.strip())
                current = para
            else:
                current = candidate
        if current.strip():
            parts.append(current.strip())
        # Hard-split any paragraph that is still too long
        result: list[str] = []
        for part in parts:
            while len(part) > max_section_chars:
                result.append(part[:max_section_chars])
                part = part[max_section_chars:]
            if part:
                result.append(part)
        return result

    lines = text.splitlines(keepends=True)
    sections: list[str] = []
    current_lines: list[str] = []

    for line in lines:
        if _HEADER_RE.match(line) and current_lines:
            # Boundary found — flush current section
            chunk = "".join(current_lines).strip()
            if chunk:
                sections.extend(_sub_split(chunk))
            current_lines = [line]
        else:
            current_lines.append(line)

    # Flush the last section
    if current_lines:
        chunk = "".join(current_lines).strip()
        if chunk:
            sections.extend(_sub_split(chunk))

    return sections if sections else [text]


def merge_graphs(graphs: list[dict]) -> dict:
    """
    Merge multiple partial knowledge graphs into one.

    - Deduplicate nodes: normalize labels (lowercase, strip punctuation),
      keep first occurrence, skip exact/near-exact duplicates
    - Deduplicate edges: if same (from_label, to_label, type) exists,
      average the weights and confidences
    - Returns merged {"nodes": [...], "edges": [...]}
    """
    _PUNCT = str.maketrans("", "", string.punctuation)

    def _norm(label: str) -> str:
        return label.lower().translate(_PUNCT).strip()

    merged_nodes: list[dict] = []
    seen_node_keys: dict[str, str] = {}  # norm_label → canonical label

    for graph in graphs:
        for node in graph.get("nodes", []):
            label = node.get("label", "").strip()
            key = _norm(label)
            if key and key not in seen_node_keys:
                seen_node_keys[key] = label
                merged_nodes.append(node)

    # Build canonical-label lookup (norm → first canonical)
    def _canonical(label: str) -> str:
        return seen_node_keys.get(_norm(label), label)

    # Deduplicate edges: accumulate weights and confidences per (from, to, type)
    edge_buckets: dict[tuple[str, str, str], list[dict]] = {}
    for graph in graphs:
        for edge in graph.get("edges", []):
            fl = _canonical(edge.get("from_label", ""))
            tl = _canonical(edge.get("to_label", ""))
            etype = edge.get("type", "relational")
            if fl and tl and fl != tl:
                key = (fl, tl, etype)
                edge_buckets.setdefault(key, []).append(edge)

    merged_edges: list[dict] = []
    for (fl, tl, etype), bucket in edge_buckets.items():
        avg_weight = sum(e.get("weight", 0.5) for e in bucket) / len(bucket)
        avg_conf = sum(e.get("confidence", 0.5) for e in bucket) / len(bucket)
        merged_edges.append({
            "from_label": fl,
            "to_label": tl,
            "type": etype,
            "weight": round(avg_weight, 4),
            "confidence": round(avg_conf, 4),
        })

    return {"nodes": merged_nodes, "edges": merged_edges}


class AnalysisService:
    """Knowledge graph extraction and zoom operations."""

    def __init__(self, db: AsyncSession, llm: LLMAdapter) -> None:
        self._db = db
        self._llm = llm

    async def analyze_l0(
        self, topic_id: str, source: Source
    ) -> AsyncGenerator[tuple[str, dict], None]:
        """
        Level-0 analysis: extract initial knowledge graph from a source.

        Splits the document into sections, runs LLM on each, then merges
        the partial graphs into one unified knowledge graph.

        Yields (event_type, data) tuples for SSE streaming.
        """
        yield "progress", {"step": "analyzing", "pct": 5}

        # Detect source language to drive all LLM output
        lang_code = detect_language(source.extracted_text)
        lang_name = language_name_for(lang_code)
        log.info("language_detected", lang_code=lang_code, lang_name=lang_name)

        # Split into sections to cover the full document
        sections = split_into_sections(source.extracted_text)
        log.info("sections_split", count=len(sections), source_id=source.id)

        # Analyze each section independently
        partial_graphs: list[dict] = []
        for i, section in enumerate(sections):
            pct = 10 + int((i / len(sections)) * 50)
            yield "progress", {"step": f"analyzing_section_{i + 1}_of_{len(sections)}", "pct": pct}

            prompt = L0_ANALYSIS_PROMPT.format(language_name=lang_name) + section
            messages = [
                {"role": "system", "content": LLULL_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
            response = ""
            async for token in await self._llm.complete(messages, stream=False):
                response += token

            graph = self._extract_json(response)
            if graph:
                partial_graphs.append(graph)
            else:
                log.warning("section_parse_failed", section_index=i, preview=response[:100])

        yield "progress", {"step": "merging_graphs", "pct": 60}

        if not partial_graphs:
            yield "error", {"code": "PARSE_FAILED", "message": "No sections could be parsed"}
            return

        # Merge partial graphs into one
        graph_data = merge_graphs(partial_graphs)

        # Consolidation: deduplicate semantically similar nodes in batches
        if len(graph_data.get("nodes", [])) > 10:
            graph_data = await self._consolidate_graph(graph_data, lang_name)

        yield "progress", {"step": "persisting", "pct": 70}

        # Persist nodes and edges
        nodes_by_label: dict[str, Node] = {}
        new_nodes = []
        new_edges = []

        for node_data in graph_data.get("nodes", []):
            node = Node(
                id=str(uuid.uuid4()),
                topic_id=topic_id,
                source_id=source.id,
                label=node_data.get("label", "Unknown"),
                description=node_data.get("description", ""),
                status="unexplored",
            )
            self._db.add(node)
            nodes_by_label[node.label] = node
            new_nodes.append(node)

        await self._db.flush()
        yield "progress", {"step": "persisting_nodes", "pct": 80}

        for edge_data in graph_data.get("edges", []):
            from_label = edge_data.get("from_label", "")
            to_label = edge_data.get("to_label", "")
            from_node = nodes_by_label.get(from_label)
            to_node = nodes_by_label.get(to_label)

            if from_node and to_node and from_node.id != to_node.id:
                edge = Edge(
                    id=str(uuid.uuid4()),
                    from_node_id=from_node.id,
                    to_node_id=to_node.id,
                    type=_normalize_edge_type(edge_data.get("type", "relational")),
                    weight=float(edge_data.get("weight", 0.5)),
                    confidence=float(edge_data.get("confidence", 0.5)),
                )
                self._db.add(edge)
                new_edges.append(edge)

        await self._db.flush()

        yield "nodes_updated", {
            "new_nodes": [{"id": n.id, "label": n.label} for n in new_nodes],
            "new_edges": [{"id": e.id} for e in new_edges],
        }

        # Generate document blocks from the extracted graph
        yield "progress", {"step": "generating_document", "pct": 85}
        doc_block_count = await self._generate_document_blocks(
            topic_id=topic_id,
            source=source,
            nodes=new_nodes,
            edges=new_edges,
            language_name=lang_name,
        )
        yield "document_updated", {"blocks": doc_block_count}

        yield "done", {"source_id": source.id, "nodes": len(new_nodes), "edges": len(new_edges)}

    async def _consolidate_graph(self, graph: dict, lang_name: str, batch_size: int = 40) -> dict:
        """
        Deduplicate semantically similar nodes in batches.

        Splits the node list into overlapping windows of `batch_size`, runs one
        LLM call per window to identify synonyms, accumulates the absorb_map,
        then applies it once to the full graph. Overlap between batches lets the
        LLM see shared context nodes so cross-batch duplicates are caught.
        Falls back to the unmodified graph if all batches fail to parse.
        """
        CONSOLIDATE_PROMPT = (
            "You have a list of concept nodes extracted from a document. "
            "Some nodes are semantically equivalent — same idea, different wording.\n\n"
            "IMPORTANT: Respond ENTIRELY in {lang_name}.\n\n"
            "Nodes:\n"
            "{nodes_list}\n\n"
            "Identify groups of nodes that mean the same thing and should be merged. "
            "For each group, choose the clearest label as the canonical one.\n\n"
            "Return a JSON object:\n"
            "{{\n"
            '  "merge": [\n'
            '    {{"into": "canonical label", "absorb": ["synonym1", "synonym2"]}}\n'
            "  ]\n"
            "}}\n\n"
            'If there are no duplicates, return {{"merge": []}}.\n'
            "Return ONLY the raw JSON object. Start with {{ and end with }}."
        )

        nodes = graph["nodes"]
        absorb_map: dict[str, str] = {}

        # Slide a window with 10-node overlap so boundary duplicates are caught
        overlap = 10
        step = batch_size - overlap
        starts = list(range(0, len(nodes), step))

        for i, start in enumerate(starts):
            batch = nodes[start : start + batch_size]
            nodes_list = "\n".join(f"- {n['label']}: {n['description']}" for n in batch)
            prompt = CONSOLIDATE_PROMPT.format(lang_name=lang_name, nodes_list=nodes_list)
            messages = [{"role": "user", "content": prompt}]

            response = ""
            async for token in await self._llm.complete(messages, stream=False):
                response += token

            instructions = self._extract_json(response)
            if not instructions:
                log.warning("consolidate_batch_parse_failed", batch=i, preview=response[:100])
                continue

            for merge in instructions.get("merge", []):
                canonical = merge.get("into", "").strip()
                if not canonical:
                    continue
                for syn in merge.get("absorb", []):
                    key = syn.lower().strip()
                    if key and key != canonical.lower():
                        absorb_map[key] = canonical

        if not absorb_map:
            return graph

        log.info("consolidate_merges", total=len(absorb_map))

        # Apply absorb_map: rewrite labels, deduplicate
        new_nodes: list[dict] = []
        seen: set[str] = set()
        for node in nodes:
            label = node["label"]
            canonical = absorb_map.get(label.lower(), label)
            if canonical.lower() not in seen:
                seen.add(canonical.lower())
                new_nodes.append({**node, "label": canonical})

        # Rewrite edges; drop self-loops created by merging
        new_edges: list[dict] = []
        for edge in graph["edges"]:
            fl = absorb_map.get(edge["from_label"].lower(), edge["from_label"])
            tl = absorb_map.get(edge["to_label"].lower(), edge["to_label"])
            if fl != tl:
                new_edges.append({**edge, "from_label": fl, "to_label": tl})

        return {"nodes": new_nodes, "edges": new_edges}

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
        edges_text = "\n".join(
            f"- {e.from_node_id} --[{e.type}]--> {e.to_node_id}" for e in edges
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
        messages = [
            {"role": "system", "content": LLULL_SYSTEM_PROMPT},
            {"role": "user", "content": prompt_content},
        ]

        response_text = ""
        async for token in await self._llm.complete(messages, stream=False):
            response_text += token

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

    async def zoom(
        self, topic_id: str, node: Node
    ) -> AsyncGenerator[tuple[str, dict], None]:
        """
        Zoom into a node: generate sub-nodes.

        Yields (event_type, data) tuples for SSE streaming.
        """
        yield "progress", {"step": "zooming", "pct": 10}

        # Get source context for this node
        source_result = await self._db.execute(
            select(Source).where(Source.id == node.source_id)
        )
        source = source_result.scalar_one_or_none()
        context = source.extracted_text[:30000] if source else ""

        # Detect source language for output consistency
        source_text = source.extracted_text if source else ""
        zoom_lang_name = language_name_for(detect_language(source_text)) if source_text else "Spanish"

        prompt = ZOOM_PROMPT.format(
            language_name=zoom_lang_name,
            label=node.label,
            description=node.description,
            context=context,
        )

        messages = [
            {"role": "system", "content": LLULL_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        response_text = ""
        async for token in await self._llm.complete(messages, stream=False):
            response_text += token

        yield "progress", {"step": "parsing_zoom", "pct": 60}

        graph_data = self._extract_json(response_text)
        if not graph_data:
            yield "error", {"code": "PARSE_FAILED", "message": "LLM returned invalid JSON for zoom"}
            return

        # Mark parent node as zoomed
        node.status = "zoomed"
        await self._db.flush()

        nodes_by_label: dict[str, Node] = {node.label: node}
        new_nodes = []
        new_edges = []

        for node_data in graph_data.get("nodes", []):
            sub_node = Node(
                id=str(uuid.uuid4()),
                topic_id=topic_id,
                source_id=node.source_id,
                label=node_data.get("label", "Unknown"),
                description=node_data.get("description", ""),
                status="unexplored",
            )
            self._db.add(sub_node)
            nodes_by_label[sub_node.label] = sub_node
            new_nodes.append(sub_node)

        await self._db.flush()

        for edge_data in graph_data.get("edges", []):
            from_label = edge_data.get("from_label", "")
            to_label = edge_data.get("to_label", "")
            from_node = nodes_by_label.get(from_label)
            to_node = nodes_by_label.get(to_label)

            if from_node and to_node and from_node.id != to_node.id:
                edge = Edge(
                    id=str(uuid.uuid4()),
                    from_node_id=from_node.id,
                    to_node_id=to_node.id,
                    type=_normalize_edge_type(edge_data.get("type", "hierarchical")),
                    weight=float(edge_data.get("weight", 0.7)),
                    confidence=float(edge_data.get("confidence", 0.8)),
                )
                self._db.add(edge)
                new_edges.append(edge)

        await self._db.flush()

        yield "nodes_updated", {
            "new_nodes": [{"id": n.id, "label": n.label} for n in new_nodes],
            "new_edges": [{"id": e.id} for e in new_edges],
        }
        yield "done", {"node_id": node.id, "sub_nodes": len(new_nodes)}

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
