import { useQuery, useQueryClient } from "@tanstack/react-query";
import mermaid from "mermaid";
import type { FC } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { ErrorMessage } from "../../components/ErrorMessage";
import { LoadingSpinner } from "../../components/LoadingSpinner";
import { useTheme } from "../../hooks/useTheme";
import { analyzeTopicStream, getGraph, zoomNodeStream } from "../../lib/api";
import type { GraphResponse } from "../../lib/types";
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

function buildMermaidGraph(graph: GraphResponse, nodeLimit = MAX_RENDER_NODES): string {
  const nodes = graph.nodes.slice(0, nodeLimit);
  const nodeIdSet = new Set(nodes.map((n) => n.id));
  const edges = graph.edges.filter(
    (e) => nodeIdSet.has(e.from_node_id) && nodeIdSet.has(e.to_node_id)
  );

  const lines: string[] = ["graph LR"];

  for (const node of nodes) {
    const safeLabel = node.label.replace(/["\[\]{}]/g, "").substring(0, 40);
    const shape = node.status === "zoomed" ? `["${safeLabel}"]` : `("${safeLabel}")`;
    lines.push(`  ${node.id.replace(/-/g, "_")}${shape}`);
  }

  for (const edge of edges) {
    const from = edge.from_node_id.replace(/-/g, "_");
    const to = edge.to_node_id.replace(/-/g, "_");
    const arrow = edge.type === "hierarchical" ? "-->" : edge.type === "causal" ? "-..->" : "---";
    lines.push(`  ${from} ${arrow} ${to}`);
  }

  return lines.join("\n");
}

export const MapTab: FC<MapTabProps> = ({
  topicId,
  onZoomComplete,
  highlightedNodeIds = [],
  onMapInteraction,
}) => {
  const queryClient = useQueryClient();
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<GraphResponse | null>(null);
  const [svgContent, setSvgContent] = useState<string>("");
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
    const nodeMap = new Map(g.nodes.map((n) => [n.label, n.description]));
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

    const definition = buildMermaidGraph(g, MAX_RENDER_NODES);
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
    setAnalyzing(true);
    setAnalyzeStatus(`Zooming into "${nodeLabel}"…`);
    setAnalyzeError("");
    try {
      await zoomNodeStream(topicId, nodeId, (event) => {
        if (event.type === "progress") {
          setAnalyzeStatus(`Zooming: ${event.data.step}`);
        } else if (event.type === "done") {
          setAnalyzeStatus(`Zoomed into ${nodeLabel} — ${event.data.sub_nodes} sub-nodes`);
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
  }, [topicId, queryClient, onZoomComplete]);

  const addZoomHandlers = useCallback((g: GraphResponse) => {
    // Run after paint so the SVG is already in the DOM
    requestAnimationFrame(() => {
      const svgEl = containerRef.current?.querySelector("svg");
      if (!svgEl) return;
      const nodeMap = new Map(g.nodes.map((n) => [n.label, n]));
      svgEl.querySelectorAll(".node").forEach((el) => {
        const labelEl = el.querySelector(".label, text");
        const label = labelEl?.textContent?.trim();
        const node = label ? nodeMap.get(label) : undefined;
        if (node && node.status === "unexplored") {
          (el as HTMLElement).style.cursor = "pointer";
          el.addEventListener("click", () => void handleZoom(node.id, node.label));
        }
      });
    });
  }, [handleZoom]);

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
          setAnalyzeStatus(`Done — ${event.data.nodes} nodes, ${event.data.edges} edges`);
          setAnalyzeProgress(100);
          // Force fresh fetch (bypass staleTime cache) after analysis completes
          void queryClient.invalidateQueries({ queryKey: ["graph", topicId] });
        } else if (event.type === "error") {
          setAnalyzeError(event.data.message);
        }
      });
    } catch (err) {
      setAnalyzeError(err instanceof Error ? err.message : "Analysis failed");
    } finally {
      setAnalyzing(false);
    }
  }, [topicId, queryClient]);

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
        <button
          className="btn btn-primary"
          onClick={() => void handleAnalyze()}
          disabled={analyzing}
          title="Analyze sources and build knowledge graph"
        >
          {analyzing ? `⏳ Analyzing… ${analyzeProgress}%` : "🧠 Analyze Sources"}
        </button>
        {graph && (
          <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>
            {graph.nodes.length} nodes · {graph.edges.length} edges
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
          <div
            className={styles.graphContainer}
            ref={containerRef}
            dangerouslySetInnerHTML={{ __html: svgContent }}
            onClick={onMapInteraction}
          />
          <div className={styles.legend} style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "0.5rem" }}>
            <div className={styles.legendItem}>
              <div className={styles.dot} style={{ background: "var(--accent)" }} />
              Unexplored node (click to zoom)
            </div>
            <div className={styles.legendItem}>
              <div className={styles.dot} style={{ background: "var(--success)" }} />
              Zoomed node
            </div>
            <div className={styles.legendItem}>
              <span>→ Relational</span>
            </div>
            <div className={styles.legendItem}>
              <span>⇒ Hierarchical</span>
            </div>
            <div className={styles.legendItem}>
              <span>⇢ Causal</span>
            </div>
          </div>
        </>
      )}
    </div>
  );
};
