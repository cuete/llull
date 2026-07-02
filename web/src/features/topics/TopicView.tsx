import { useQuery } from "@tanstack/react-query";
import type { FC } from "react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ErrorMessage } from "../../components/ErrorMessage";
import { LoadingSpinner } from "../../components/LoadingSpinner";
import { getDocument, getGraph, getTopic } from "../../lib/api";
import { ChatTab } from "../chat/ChatTab";
import { DocumentTab } from "../document/DocumentTab";
import { MapTab } from "../map/MapTab";
import { SourcesTab } from "../sources/SourcesTab";
import styles from "./TopicView.module.css";

type TabId = "chat" | "map" | "document" | "sources";

const TABS: { id: TabId; label: string; icon: string }[] = [
  { id: "chat", label: "Chat", icon: "💬" },
  { id: "map", label: "Map", icon: "🗺️" },
  { id: "document", label: "Document", icon: "📄" },
  { id: "sources", label: "Sources", icon: "📁" },
];

export const TopicView: FC = () => {
  const { id } = useParams<{ id: string }>();
  const [activeTab, setActiveTab] = useState<TabId>("chat");
  const [pendingZoomMessage, setPendingZoomMessage] = useState<string | null>(null);
  // Chat → Map: node IDs to highlight after an assistant response
  const [highlightedNodeIds, setHighlightedNodeIds] = useState<string[]>([]);
  // Document → Chat: pending message auto-sent when Document block is tapped
  const [pendingDocMessage, setPendingDocMessage] = useState<string | null>(null);
  // Map → Document: block ID to highlight when user switches to Document tab after zoom
  const [highlightedDocBlockId, setHighlightedDocBlockId] = useState<string | null>(null);

  const { data: topic, isLoading, error } = useQuery({
    queryKey: ["topic", id],
    queryFn: () => getTopic(id!),
    enabled: !!id,
    staleTime: 60_000,
  });

  // Pre-fetch graph for keyword matching on Document block tap (#4)
  const { data: graph } = useQuery({
    queryKey: ["graph", id],
    queryFn: () => getGraph(id!),
    enabled: !!id,
    staleTime: 60_000,
  });

  // Pre-fetch document for Map → Document block highlight on zoom
  const { data: docData } = useQuery({
    queryKey: ["document", id],
    queryFn: () => getDocument(id!),
    enabled: !!id,
    staleTime: 30_000,
  });

  if (!id) return <div className={styles.notFound}>Topic not found</div>;

  if (isLoading) return <LoadingSpinner label="Loading topic…" />;
  if (error) return <ErrorMessage error={error} />;
  if (!topic) return <div className={styles.notFound}>Topic not found</div>;

  return (
    <div className={styles.page}>
      <div className={styles.topicHeader}>
        <div className={styles.breadcrumb}>
          <Link to="/" className={styles.breadcrumbLink}>Topics</Link>
          <span className={styles.breadcrumbSep}> / </span>
          <span className={styles.breadcrumbCurrent}>{topic.title}</span>
        </div>
        <nav className={styles.tabs} role="tablist">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              role="tab"
              aria-selected={activeTab === tab.id}
              className={`${styles.tab} ${activeTab === tab.id ? styles.active : ""}`}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.icon} {tab.label}
            </button>
          ))}
        </nav>
      </div>

      <div className={styles.tabContent} role="tabpanel">
        {activeTab === "chat" && (
          <ChatTab
            topicId={id}
            pendingZoomMessage={pendingZoomMessage}
            onPendingZoomConsumed={() => setPendingZoomMessage(null)}
            pendingDocMessage={pendingDocMessage}
            onPendingDocConsumed={() => setPendingDocMessage(null)}
            onAssistantResponse={(mentionedNodeIds) => {
              setHighlightedNodeIds(mentionedNodeIds);
              // Auto-clear highlights after 5 seconds
              setTimeout(() => setHighlightedNodeIds([]), 5000);
            }}
          />
        )}
        {activeTab === "map" && (
          <MapTab
            topicId={id}
            highlightedNodeIds={highlightedNodeIds}
            onZoomComplete={(nodeLabel) => {
              setActiveTab("chat");
              setPendingZoomMessage(
                `Zoomed into "${nodeLabel}". Analyze the sub-concepts discovered and explain how they relate to each other and to the parent concept. Use bullet points, plain markdown only.`
              );
              // Map → Document: find block mentioning this node label and queue highlight
              if (docData?.blocks.length) {
                const lower = nodeLabel.toLowerCase();
                const match = docData.blocks.find((b) =>
                  b.content_md.toLowerCase().includes(lower)
                );
                if (match) {
                  setHighlightedDocBlockId(match.id);
                }
              }
            }}
            onMapInteraction={() => setHighlightedNodeIds([])}
          />
        )}
        {activeTab === "document" && (
          <DocumentTab
            topicId={id}
            highlightedDocBlockId={highlightedDocBlockId}
            onHighlightConsumed={() => setHighlightedDocBlockId(null)}
            onBlockTap={(blockContent) => {
              // Document → Chat: switch to Chat and auto-send a question about the block
              const preview = blockContent.slice(0, 200);
              setPendingDocMessage(`Tell me more about: ${preview}`);
              setActiveTab("chat");
              // Feature #4: also highlight graph nodes matching keywords in the block
              if (graph?.nodes.length) {
                const lowerContent = blockContent.toLowerCase();
                const matchedIds = graph.nodes
                  .filter((n) => lowerContent.includes(n.label.toLowerCase()))
                  .map((n) => n.id);
                if (matchedIds.length) {
                  setHighlightedNodeIds(matchedIds);
                  setTimeout(() => setHighlightedNodeIds([]), 5000);
                }
              }
            }}
          />
        )}
        {activeTab === "sources" && <SourcesTab topicId={id} />}
      </div>
    </div>
  );
};
