"""Analysis service — level 0 graph extraction and zoom operations."""
from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.graph import Edge, Node
from app.models.source import Source
from app.services.llm.base import LLMAdapter
from app.services.prompt import LLULL_SYSTEM_PROMPT

log = structlog.get_logger()

# L0 analysis prompt
L0_ANALYSIS_PROMPT = """Analyze the following document content and extract a knowledge graph.

Return a JSON object with this exact structure:
{
  "nodes": [
    {
      "label": "short concept name (1-5 words)",
      "description": "atomic idea in 1-2 sentences"
    }
  ],
  "edges": [
    {
      "from_label": "label of source node",
      "to_label": "label of target node",
      "type": "relational|hierarchical|causal",
      "weight": 0.7,
      "confidence": 0.8
    }
  ]
}

Guidelines:
- Extract 5-15 key concepts as nodes
- Each node should represent one atomic idea
- Identify meaningful relationships between nodes
- Weight: 0-1, strength of relationship
- Confidence: 0-1, how certain you are based on the text
- Only create edges between nodes in your list

Document content:
"""

ZOOM_PROMPT = """Zoom into the following concept from a knowledge graph and generate sub-nodes.

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

Generate 3-7 sub-nodes that elaborate on the parent concept."""


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

        Yields (event_type, data) tuples for SSE streaming.
        """
        yield "progress", {"step": "analyzing", "pct": 10}

        # Build prompt with source text
        prompt_content = L0_ANALYSIS_PROMPT + (source.extracted_text[:50000])
        messages = [
            {"role": "system", "content": LLULL_SYSTEM_PROMPT},
            {"role": "user", "content": prompt_content},
        ]

        # Collect LLM response
        response_text = ""
        token_count = 0
        async for token in await self._llm.complete(messages, stream=False):
            response_text += token
            token_count += 1

        yield "progress", {"step": "parsing_graph", "pct": 60}

        # Parse the JSON response
        graph_data = self._extract_json(response_text)
        if not graph_data:
            yield "error", {"code": "PARSE_FAILED", "message": "LLM returned invalid JSON"}
            return

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
        yield "progress", {"step": "persisting_nodes", "pct": 75}

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
                    type=edge_data.get("type", "relational"),
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
        yield "done", {"source_id": source.id, "nodes": len(new_nodes), "edges": len(new_edges)}

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

        prompt = ZOOM_PROMPT.format(
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
                    type=edge_data.get("type", "hierarchical"),
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
        """Extract JSON from LLM response, handling markdown code blocks."""
        # Try direct parse
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try extracting from code blocks
        import re

        patterns = [
            r"```json\s*([\s\S]*?)\s*```",
            r"```\s*([\s\S]*?)\s*```",
            r"\{[\s\S]*\}",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                candidate = match.group(1) if "```" in pattern else match.group(0)
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    continue

        log.warning("json_extract_failed", response_preview=text[:200])
        return None
