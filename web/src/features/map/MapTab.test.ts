// @vitest-environment jsdom
import mermaid from "mermaid";
import { describe, expect, it } from "vitest";
import type { GraphEdge, GraphNode } from "../../lib/types";
import { buildMermaidGraph } from "./MapTab";

function node(id: string, overrides: Partial<GraphNode> = {}): GraphNode {
  return {
    id,
    topic_id: "t",
    source_id: "s",
    label: `Node ${id}`,
    description: "",
    status: "unexplored",
    level: 0,
    parent_id: null,
    coverage: null,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function edge(from: string, to: string, overrides: Partial<GraphEdge> = {}): GraphEdge {
  return {
    id: `${from}-${to}`,
    from_node_id: from,
    to_node_id: to,
    type: "relational",
    weight: 0.5,
    confidence: 0.5,
    basis: "read",
    status: "active",
    evidence: null,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("buildMermaidGraph", () => {
  const graph = {
    nodes: ["a", "b", "c", "d"].map((id) => node(id)),
    edges: [
      edge("a", "b", { basis: "read", type: "hierarchical" }),
      edge("a", "c", { basis: "read" }),
      edge("b", "c", { basis: "sampled", type: "causal" }),
      edge("b", "d", { basis: "sampled" }),
      edge("c", "d", { basis: "suggested" }),
      edge("a", "d", { status: "unsupported" }),
    ],
  };

  it("draws each link by how it is grounded", () => {
    const definition = buildMermaidGraph(graph);
    expect(definition).toContain("a ==> b"); // read, directed
    expect(definition).toContain("a === c"); // read
    expect(definition).toContain("b --> c"); // sampled, directed
    expect(definition).toContain("b --- d"); // sampled
    expect(definition).toContain("c -. ? .- d"); // suggested
    expect(definition).toContain("a -. ✗ .- d"); // no longer supported
  });

  it("produces a definition mermaid accepts", async () => {
    mermaid.initialize({ startOnLoad: false });
    await expect(mermaid.parse(buildMermaidGraph(graph))).resolves.toBeTruthy();
  });
});
