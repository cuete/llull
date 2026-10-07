import { useQuery, useQueryClient } from "@tanstack/react-query";
import mermaid from "mermaid";
import type { FC } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { ErrorMessage } from "../../components/ErrorMessage";
import { LoadingSpinner } from "../../components/LoadingSpinner";
import { usePanZoom } from "../../hooks/usePanZoom";
import { useReadOnly } from "../../hooks/useReadOnly";
import { useTheme } from "../../hooks/useTheme";
import { analyzeTopicStream, getGraph, zoomNodeStream } from "../../lib/api";
import type { GraphEdge, GraphNode, GraphResponse } from "../../lib/types";
import styles from "./MapTab.module.css";

interface MapTabProps {
  topicId: string;
  onZoomComplete?: (nodeLabel: string, subNodeLabels: string[]) => void;
  /** Node IDs to visually highlight (from Chat mentions) */
  highlightedNodeIds?: string[];
  /** Called when the user interacts with the map (clears highlights) */
  onMapInteraction?: () => void;
}

const MAX_RENDER_NODES = 80;

export interface NodeColors {
  unexplored: string;
  zoomed: string;
}

// Same colours as the legend under the map (--accent / --success)
const DEFAULT_NODE_COLORS: NodeColors = { unexplored: "#6366f1", zoomed: "#22c55e" };

/** The legend's colours as currently themed, so the map matches it in light and dark. */
function themedNodeColors(): NodeColors {
  const css = getComputedStyle(document.documentElement);
  return {
    unexplored: css.getPropertyValue("--accent").trim() || DEFAULT_NODE_COLORS.unexplored,
    zoomed: css.getPropertyValue("--success").trim() || DEFAULT_NODE_COLORS.zoomed,
  };
}

export function buildMermaidGraph(
  graph: GraphResponse,
  nodeLimit = MAX_RENDER_NODES,
  colors: NodeColors = DEFAULT_NODE_COLORS,
): string {
  const nodes = graph.nodes.slice(0, nodeLimit);
  const nodeIdSet = new Set(nodes.map((n) => n.id));
  const edges = graph.edges.filter(
    (e) => nodeIdSet.has(e.from_node_id) && nodeIdSet.has(e.to_node_id)
  );

  const lines: string[] = ["graph LR"];

  for (const node of nodes) {
    const safeLabel = node.label.replace(/["\[\]{}]/g, "").substring(0, 40);
    const shape = node.status === "zoomed" ? `["${safeLabel}"]` : `("${safeLabel}")`;
    lines.push(`  ${node.id.replace(/-/g, "_")}${shape}:::${node.status}`);
  }

  // Outline each node in its legend colour: explored (zoomed) vs not yet explored
  lines.push(`  classDef unexplored stroke:${colors.unexplored},stroke-width:2px`);
  lines.push(`  classDef zoomed stroke:${colors.zoomed},stroke-width:3px`);

  for (const edge of edges) {
    const from = edge.from_node_id.replace(/-/g, "_");
    const to = edge.to_node_id.replace(/-/g, "_");
    lines.push(`  ${from} ${edgeArrow(edge)} ${to}`);
  }

  return lines.join("\n");
}

/**
 * Line style shows how well a link is grounded: thick = read from the node's full text,
 * normal = inferred from a sample, dotted = only suggested (or no longer supported).
 * An arrowhead marks hierarchical and causal links.
 */
function edgeArrow(edge: GraphEdge): string {
  const directed = edge.type !== "relational";
  if (edge.status === "unsupported") return "-. ✗ .-";
  if (edge.basis === "suggested") return "-. ? .-";
  if (edge.basis === "read") return directed ? "==>" : "===";
  return directed ? "-->" : "---";
}

function nodeTooltip(node: GraphNode): string {
  const parts = [node.description];
  const facts: string[] = [];
  if (node.coverage !== null) {
    facts.push(`Covers ${(node.coverage * 100).toFixed(node.coverage < 0.1 ? 1 : 0)}% of the source`);
  }
  facts.push(node.status === "zoomed" ? "explored" : "not explored yet — click to open its sub-concepts");
  parts.push(facts.join(" · "));
  return parts.join("\n\n");
}

export const MapTab: FC<MapTabProps> = ({
  topicId,
  onZoomComplete,
  highlightedNodeIds = [],
  onMapInteraction,
}) => {
  const queryClient = useQueryClient();
  const readOnly = useReadOnly();
  const viewportRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<GraphResponse | null>(null);
  const [svgContent, setSvgContent] = useState<string>("");
  const panZoom = usePanZoom(viewportRef, containerRef, svgContent);
  const [renderError, setRenderError] = useState<string>("");
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeProgress, setAnalyzeProgress] = useState<number>(0);
  const [analyzeStatus, setAnalyzeStatus] = useState<string>("");
  const [analyzeError, setAnalyzeError] = useState<string>("");
  const { theme } = useTheme();

  // Re-initialize mermaid when theme changes
  useEffect(() => {
    const isDark = theme === "dark";
    mermaid.initialize({
      startOnLoad: false,
      maxTextSize: 500_000,
      theme: "base",
      themeVariables: isDark
        ? {
            primaryColor: "#374151",
            primaryTextColor: "#f9fafb",
            primaryBorderColor: "#6b7280",
            lineColor: "#9ca3af",
            background: "transparent",
            mainBkg: "#374151",
            nodeBorder: "#6b7280",
          }
        : {
            primaryColor: "#e5e7eb",
            primaryTextColor: "#111827",
            primaryBorderColor: "#9ca3af",
            lineColor: "#6b7280",
            background: "transparent",
            mainBkg: "#f3f4f6",
            nodeBorder: "#9ca3af",
          },
      securityLevel: "loose",
    });
    // Re-render current graph when theme changes
    if (graphRef.current) {
      void renderGraph(graphRef.current);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [theme]);

  const { data: graph, isLoading, error } = useQuery({
    queryKey: ["graph", topicId],
    queryFn: () => getGraph(topicId),
    staleTime: 60_000,
  });

  const addTooltipsToSvg = useCallback((g: GraphResponse) => {
    const svgEl = containerRef.current?.querySelector("svg");
    if (!svgEl || !g.nodes.length) return;
    const nodeMap = new Map(g.nodes.map((n) => [n.label, nodeTooltip(n)]));
    svgEl.querySelectorAll(".node").forEach((el) => {
      const labelEl = el.querySelector(".label, text");
      const label = labelEl?.textContent?.trim();
      if (label && nodeMap.has(label)) {
        // Remove any existing title
        el.querySelector("title")?.remove();
        const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
        title.textContent = nodeMap.get(label) ?? "";
        el.prepend(title);
      }
    });
  }, []);

  const renderGraph = useCallback(async (g: GraphResponse) => {
    if (!g.nodes.length) {
      setSvgContent("");
      return;
    }

    const definition = buildMermaidGraph(g, MAX_RENDER_NODES, themedNodeColors());
    try {
      const id = `graph-${topicId}-${Date.now()}`;
      const { svg } = await mermaid.render(id, definition);
      setSvgContent(svg);
      setRenderError("");
    } catch (err) {
      setRenderError(err instanceof Error ? err.message : "Failed to render graph");
    }
  }, [topicId]);

  useEffect(() => {
    if (graph) {
      graphRef.current = graph;
      void renderGraph(graph);
    }
  }, [graph, renderGraph]);

  const handleZoom = useCallback(async (nodeId: string, nodeLabel: string) => {
    if (readOnly) return;
    setAnalyzing(true);
    setAnalyzeStatus(`Zooming into "${nodeLabel}"…`);
    setAnalyzeError("");
    try {
      await zoomNodeStream(topicId, nodeId, (event) => {
        if (event.type === "progress") {
          setAnalyzeStatus(`Zooming: ${event.data.step}`);
        } else if (event.type === "done") {
          const { sub_nodes, new_links = 0, revised_links = 0 } = event.data;
          setAnalyzeStatus(
            `Zoomed into ${nodeLabel} — ${sub_nodes} sub-nodes, ${new_links} new links, ${revised_links} links revised`,
          );
          void queryClient.invalidateQueries({ queryKey: ["graph", topicId] });
          // Fire callback to trigger auto-chat on zoom completion
          onZoomComplete?.(nodeLabel, []);
        } else if (event.type === "error") {
          setAnalyzeError(event.data.message);
        }
      });
    } catch (err) {
      setAnalyzeError(err instanceof Error ? err.message : "Zoom failed");
    } finally {
      setAnalyzing(false);
    }
  }, [readOnly, topicId, queryClient, onZoomComplete]);

  // Node click listeners are bound once per rendered SVG and call the latest handler
  const handleZoomRef = useRef(handleZoom);
  handleZoomRef.current = handleZoom;

  const addZoomHandlers = useCallback((g: GraphResponse) => {
    if (readOnly) return;
    // Run after paint so the SVG is already in the DOM
    requestAnimationFrame(() => {
      const svgEl = containerRef.current?.querySelector("svg");
      if (!svgEl) return;
      const nodeMap = new Map(g.nodes.map((n) => [n.label, n]));
      svgEl.querySelectorAll(".node").forEach((el) => {
        const labelEl = el.querySelector(".label, text");
        const label = labelEl?.textContent?.trim();
        const node = label ? nodeMap.get(label) : undefined;
        const element = el as HTMLElement;
        // This runs again whenever its inputs change while the same SVG is on screen;
        // binding twice would send two zoom requests for one click.
        if (node && node.status === "unexplored" && !element.dataset.zoomBound) {
          element.dataset.zoomBound = "true";
          element.style.cursor = "pointer";
          element.addEventListener("click", () => void handleZoomRef.current(node.id, node.label));
        }
      });
    });
  }, [readOnly]);

  // Add tooltips and zoom handlers after SVG renders (runs on every new svgContent)
  useEffect(() => {
    if (svgContent && graphRef.current) {
      // Wait for React to paint the SVG into the DOM
      requestAnimationFrame(() => {
        if (graphRef.current) {
          addTooltipsToSvg(graphRef.current);
          addZoomHandlers(graphRef.current);
        }
      });
    }
  }, [svgContent, addTooltipsToSvg, addZoomHandlers]);

  // Apply highlight pulse to mentioned nodes; clears on map interaction
  useEffect(() => {
    const svgEl = containerRef.current?.querySelector("svg");
    if (!svgEl || !graphRef.current) return;

    // Remove existing highlights
    svgEl.querySelectorAll(".node").forEach((el) => {
      (el as HTMLElement).style.removeProperty("filter");
      (el as HTMLElement).style.removeProperty("outline");
      el.classList.remove("llull-highlight");
    });

    if (!highlightedNodeIds.length) return;

    const idSet = new Set(highlightedNodeIds);
    const nodeMap = new Map(graphRef.current.nodes.map((n) => [n.id, n.label]));

    svgEl.querySelectorAll(".node").forEach((el) => {
      const labelEl = el.querySelector(".label, text");
      const label = labelEl?.textContent?.trim();
      // Match by label → id lookup
      const matchedNode = graphRef.current!.nodes.find(
        (n) => n.label === label && idSet.has(n.id)
      );
      if (matchedNode) {
        // Subtle drop-shadow pulse to indicate mention
        (el as HTMLElement).style.filter =
          "drop-shadow(0 0 6px var(--accent, #6366f1)) drop-shadow(0 0 12px var(--accent, #6366f1))";
        el.classList.add("llull-highlight");
      }
    });
    void nodeMap; // silence unused-var lint
  }, [highlightedNodeIds]);

  const handleAnalyze = useCallback(async () => {
    if (readOnly) return;
    const hasMap = (graphRef.current?.nodes.length ?? 0) > 0;
    if (
      hasMap &&
      !window.confirm("Re-analyze the sources? This replaces the current map, including zoomed layers.")
    ) {
      return;
    }
    setAnalyzing(true);
    setAnalyzeProgress(0);
    setAnalyzeStatus("Starting analysis…");
    setAnalyzeError("");

    try {
      await analyzeTopicStream(topicId, (event) => {
        if (event.type === "progress") {
          setAnalyzeProgress(event.data.pct);
          setAnalyzeStatus(event.data.step.replace(/_/g, " "));
        } else if (event.type === "document_updated") {
          setAnalyzeStatus(`Document ready (${event.data.blocks} blocks)`);
        } else if (event.type === "done") {
          const { nodes, edges, sampled, read_tokens, content_tokens } = event.data;
          const share =
            sampled && read_tokens && content_tokens
              ? ` · read ${Math.round((read_tokens / content_tokens) * 100)}% of the text`
              : "";
          setAnalyzeStatus(`Done — ${nodes} nodes, ${edges} edges${share}`);
          setAnalyzeProgress(100);
          // Force fresh fetch (bypass staleTime cache) after analysis completes
          void queryClient.invalidateQueries({ queryKey: ["graph", topicId] });
        } else if (event.type === "error") {
          setAnalyzeError(event.data.message);
        }
      }, hasMap);
    } catch (err) {
      setAnalyzeError(err instanceof Error ? err.message : "Analysis failed");
    } finally {
      setAnalyzing(false);
    }
  }, [readOnly, topicId, queryClient]);

  if (isLoading) return <LoadingSpinner label="Loading knowledge graph…" />;
  if (error) return <ErrorMessage error={error} />;

  const isEmpty = !graph || graph.nodes.length === 0;

  return (
    <div className={styles.container}>
      <div className={styles.toolbar}>
        <button
          className="btn btn-secondary"
          onClick={() => void queryClient.invalidateQueries({ queryKey: ["graph", topicId] })}
        >
          🔄 Refresh
        </button>
        {!readOnly && (
          <button
            className="btn btn-primary"
            onClick={() => void handleAnalyze()}
            disabled={analyzing}
            title="Analyze sources and build knowledge graph"
          >
            {analyzing
              ? `⏳ Analyzing… ${analyzeProgress}%`
              : isEmpty
                ? "🧠 Analyze Sources"
                : "🧠 Re-analyze"}
          </button>
        )}
        {graph && (
          <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>
            {graph.nodes.length} nodes · {graph.edges.length} edges
          </span>
        )}
        {!isEmpty && (
          <span
            style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}
            title="How each link is grounded in the text"
          >
            Links: ━ read · ─ sampled · ┄ suggested
          </span>
        )}
      </div>

      {analyzing && (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.4rem" }}>
          <div
            style={{
              height: "6px",
              background: "var(--border)",
              borderRadius: "3px",
              overflow: "hidden",
            }}
          >
            <div
              style={{
                height: "100%",
                width: `${analyzeProgress}%`,
                background: "var(--accent)",
                borderRadius: "3px",
                transition: "width 0.3s ease",
              }}
            />
          </div>
          <span style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
            {analyzeStatus}
          </span>
        </div>
      )}

      {!analyzing && analyzeStatus && !analyzeError && (
        <span style={{ fontSize: "0.8rem", color: "var(--success)" }}>
          ✅ {analyzeStatus}
        </span>
      )}

      {renderError && <ErrorMessage error={new Error(renderError)} />}
      {analyzeError && <ErrorMessage error={new Error(analyzeError)} />}

      {graph && graph.nodes.length > MAX_RENDER_NODES && (
        <div style={{ fontSize: "0.8rem", color: "var(--text-muted)", padding: "0.25rem 0" }}>
          Showing {MAX_RENDER_NODES} of {graph.nodes.length} nodes. Click nodes to zoom into sub-concepts.
        </div>
      )}

      {isEmpty ? (
        <div className={styles.emptyState}>
          <span className={styles.emptyIcon}>🗺️</span>
          <p>No knowledge graph yet</p>
          <p style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>
            Add sources and run analysis to build the graph
          </p>
        </div>
      ) : (
        <>
          <div className={styles.graphContainer} ref={viewportRef} onClick={onMapInteraction}>
            <div
              className={styles.graphContent}
              ref={containerRef}
              dangerouslySetInnerHTML={{ __html: svgContent }}
            />
            <div className={styles.viewControls} onClick={(e) => e.stopPropagation()}>
              <button className="btn btn-secondary" onClick={panZoom.zoomOut} title="Zoom out" aria-label="Zoom out">
                −
              </button>
              <span className={styles.viewScale}>{Math.round(panZoom.scale * 100)}%</span>
              <button className="btn btn-secondary" onClick={panZoom.zoomIn} title="Zoom in" aria-label="Zoom in">
                +
              </button>
              <button className="btn btn-secondary" onClick={panZoom.fit} title="Fit the whole map" aria-label="Fit the whole map">
                ⤢
              </button>
            </div>
          </div>
          <div style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
            Drag to move · scroll or pinch to zoom the view
          </div>
          <div className={styles.legend} style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "0.5rem" }}>
            <div className={styles.legendItem}>
              <div className={styles.dot} style={{ background: "var(--accent)" }} />
              Unexplored node (click to open its sub-concepts)
            </div>
            <div className={styles.legendItem}>
              <div className={styles.dot} style={{ background: "var(--success)" }} />
              Zoomed node
            </div>
            <div className={styles.legendItem}>
              <span>— Related</span>
            </div>
            <div className={styles.legendItem}>
              <span>→ Hierarchical or causal</span>
            </div>
          </div>
        </>
      )}
    </div>
  );
};
