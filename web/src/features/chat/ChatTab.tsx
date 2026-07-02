import { useQuery, useQueryClient } from "@tanstack/react-query";
import { marked } from "marked";
import mermaid from "mermaid";
import type { FC } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { ErrorMessage } from "../../components/ErrorMessage";
import { LoadingSpinner } from "../../components/LoadingSpinner";
import { addDocumentBlock, getChatHistory, getGraph } from "../../lib/api";
import type { ConversationMessage } from "../../lib/types";
import { useSSEStream } from "../../hooks/useSSEStream";
import styles from "./ChatTab.module.css";

// Minimum word count to show "Save to Document" button
const ANALYTICAL_WORD_THRESHOLD = 150;

function countWords(text: string): number {
  return text.trim().split(/\s+/).filter(Boolean).length;
}

// Configure marked for safe HTML output
marked.setOptions({ breaks: true });

/** Build a compact mermaid LR block from graph data (top 8 nodes). */
function buildMermaidFromGraph(graph: import("../../lib/types").GraphResponse): string {
  const nodes = graph.nodes.slice(0, 8);
  const nodeIds = new Set(nodes.map(n => n.id));
  const edges = graph.edges.filter(e => nodeIds.has(e.from_node_id) && nodeIds.has(e.to_node_id));
  const idMap = new Map(nodes.map((n, i) => [n.id, `n${i}`]));
  const lines = ["graph LR"];
  for (const n of nodes) {
    const safe = n.label.replace(/["|\[\]]/g, "").substring(0, 35);
    lines.push(`  ${idMap.get(n.id)}("${safe}")`);
  }
  for (const e of edges) {
    const from = idMap.get(e.from_node_id);
    const to = idMap.get(e.to_node_id);
    if (from && to) lines.push(`  ${from} ${e.type === "hierarchical" ? "-->" : "---"} ${to}`);
  }
  return "\`\`\`mermaid\n" + lines.join("\n") + "\n\`\`\`";
}

// Initialize mermaid
mermaid.initialize({ startOnLoad: false, theme: "dark", securityLevel: "loose" });

interface ChatTabProps {
  topicId: string;
  initialMessage?: string;
  pendingZoomMessage?: string | null;
  onPendingZoomConsumed?: () => void;
  /** Auto-send this message (from Document tab block tap) */
  pendingDocMessage?: string | null;
  onPendingDocConsumed?: () => void;
  /** Called after each assistant response with matched graph node IDs */
  onAssistantResponse?: (mentionedNodeIds: string[]) => void;
}

/** Strip ```json ... ``` blocks from assistant messages before rendering. */
function stripJsonBlocks(content: string): string {
  return content.replace(/```json[\s\S]*?```/g, "").trim();
}

function renderMarkdown(content: string): string {
  try {
    return marked.parse(stripJsonBlocks(content)) as string;
  } catch {
    return content;
  }
}

export const ChatTab: FC<ChatTabProps> = ({
  topicId,
  initialMessage,
  pendingZoomMessage,
  onPendingZoomConsumed,
  pendingDocMessage,
  onPendingDocConsumed,
  onAssistantResponse,
}) => {
  const queryClient = useQueryClient();
  const [input, setInput] = useState(initialMessage ?? "");
  const [streamingContent, setStreamingContent] = useState("");
  const [localMessages, setLocalMessages] = useState<ConversationMessage[]>([]);
  const [zoomLevel, setZoomLevel] = useState(0);
  const [messageLevels, setMessageLevels] = useState<Record<string, number>>({});
  // Track which message IDs have been saved to the document
  const [savedToDocIds, setSavedToDocIds] = useState<Set<string>>(new Set());
  const [savingToDocId, setSavingToDocId] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const mermaidRef = useRef<Record<string, boolean>>({});
  // Prevent double-triggering the L0 starter message
  const starterTriggeredRef = useRef(false);
  // After starter response, append mermaid chart once
  const mermaidAppendedRef = useRef(false);
  const graphRef = useRef<import("../../lib/types").GraphResponse | null>(null);
  // Track whether pending zoom message has been consumed to avoid double-fire
  const zoomMessageConsumedRef = useRef<string | null>(null);
  // Track whether pending doc message has been consumed to avoid double-fire
  const docMessageConsumedRef = useRef<string | null>(null);
  // Accumulate streamed content so onDone can inspect it for node mentions
  const lastStreamedContentRef = useRef<string>("");

  const { data: history, isLoading, error } = useQuery({
    queryKey: ["chat-history", topicId],
    queryFn: () => getChatHistory(topicId),
    staleTime: 0,
  });

  const { data: graph } = useQuery({
    queryKey: ["graph", topicId],
    queryFn: () => getGraph(topicId),
    staleTime: 30_000,
    // Only fetch once history is confirmed empty — avoids redundant load
    enabled: history !== undefined && history.length === 0,
  });

  // Keep graphRef in sync so onDone closure can access latest graph
  if (graph) graphRef.current = graph;

  const allMessages = [
    ...(history ?? []),
    ...localMessages,
  ];

  // Current zoom level at time of sending — captured when stream starts
  const pendingZoomLevelRef = useRef(0);

  const { isStreaming, startStream, stopStream } = useSSEStream({
    onChunk: (chunk) => {
      lastStreamedContentRef.current += chunk;
      setStreamingContent((prev) => prev + chunk);
    },
    onDone: (event?: { message_id?: string }) => {
      const msgId = event?.message_id;
      if (msgId) {
        setMessageLevels((prev) => ({ ...prev, [msgId]: pendingZoomLevelRef.current }));
      }
      // Notify TopicView of node mentions in the completed response
      if (onAssistantResponse && graphRef.current && lastStreamedContentRef.current) {
        const content = lastStreamedContentRef.current;
        const matchedIds = graphRef.current.nodes
          .filter((n) =>
            content.toLowerCase().includes(n.label.toLowerCase())
          )
          .map((n) => n.id);
        onAssistantResponse(matchedIds);
      }
      lastStreamedContentRef.current = "";
      setStreamingContent("");
      setLocalMessages([]);  // clear optimistic messages — history reload will repopulate
      queryClient.invalidateQueries({ queryKey: ["chat-history", topicId] });
      // mermaid chart is appended by backend on first message
    },
    onError: (err) => {
      setStreamingContent("");
      console.error("Chat SSE error:", err);
    },
  });

  // Auto-send L0 starter message when history is empty and graph has nodes
  useEffect(() => {
    if (
      !starterTriggeredRef.current &&
      history !== undefined &&
      history.length === 0 &&
      localMessages.length === 0 &&
      graph !== undefined &&
      graph.nodes.length > 0 &&
      !isStreaming
    ) {
      starterTriggeredRef.current = true;
      pendingZoomLevelRef.current = 0;
      const starterMsg = "List the key themes from the analyzed sources as a numbered markdown list. For each theme, write one sentence description. Plain markdown only � no JSON, no code blocks, no diagrams.";
      const tempMsg: ConversationMessage = {
        id: `temp-starter-${Date.now()}`,
        topic_id: topicId,
        role: "user",
        content: starterMsg,
        created_at: new Date().toISOString(),
      };
      setLocalMessages([tempMsg]);
      startStream(`/topics/${topicId}/chat`, { message: starterMsg });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [history, graph]);

  // Auto-send pendingZoomMessage when it arrives and we're not already streaming
  useEffect(() => {
    if (!pendingZoomMessage || isStreaming) return;
    // Guard against re-firing on the same message value
    if (zoomMessageConsumedRef.current === pendingZoomMessage) return;
    zoomMessageConsumedRef.current = pendingZoomMessage;

    onPendingZoomConsumed?.();

    const tempMsg: ConversationMessage = {
      id: `temp-zoom-${Date.now()}`,
      topic_id: topicId,
      role: "user",
      content: pendingZoomMessage,
      created_at: new Date().toISOString(),
    };
    setLocalMessages((prev) => [...prev, tempMsg]);
    pendingZoomLevelRef.current = (pendingZoomLevelRef.current ?? 0) + 1;
    startStream(`/topics/${topicId}/chat`, { message: pendingZoomMessage });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingZoomMessage, isStreaming]);

  // Auto-send pendingDocMessage (from Document block tap) when not already streaming
  useEffect(() => {
    if (!pendingDocMessage || isStreaming) return;
    if (docMessageConsumedRef.current === pendingDocMessage) return;
    docMessageConsumedRef.current = pendingDocMessage;

    onPendingDocConsumed?.();

    lastStreamedContentRef.current = "";
    const tempMsg: ConversationMessage = {
      id: `temp-doc-${Date.now()}`,
      topic_id: topicId,
      role: "user",
      content: pendingDocMessage,
      created_at: new Date().toISOString(),
    };
    setLocalMessages((prev) => [...prev, tempMsg]);
    startStream(`/topics/${topicId}/chat`, { message: pendingDocMessage });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingDocMessage, isStreaming]);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [allMessages, streamingContent, scrollToBottom]);

  // Render mermaid diagrams after content updates
  useEffect(() => {
    const renderMermaid = async () => {
      const elements = document.querySelectorAll<HTMLElement>(".language-mermaid:not([data-rendered])");
      for (const el of elements) {
        const code = el.textContent ?? "";
        const id = `mermaid-${Math.random().toString(36).slice(2)}`;
        if (mermaidRef.current[id]) continue;
        mermaidRef.current[id] = true;
        try {
          const { svg } = await mermaid.render(id, code);
          el.innerHTML = svg;
          el.setAttribute("data-rendered", "true");
        } catch {
          // leave as text
        }
      }
    };
    void renderMermaid();
  }, [allMessages, streamingContent]);

  const sendMessage = useCallback(() => {
    const trimmed = input.trim();
    if (!trimmed || isStreaming) return;

    // Capture current zoom level for the outgoing message
    pendingZoomLevelRef.current = zoomLevel;

    // Reset streamed content tracker for new stream
    lastStreamedContentRef.current = "";

    // Add user message optimistically
    const tempMsg: ConversationMessage = {
      id: `temp-${Date.now()}`,
      topic_id: topicId,
      role: "user",
      content: trimmed,
      created_at: new Date().toISOString(),
    };
    setLocalMessages((prev) => [...prev, tempMsg]);
    setInput("");

    startStream(`/topics/${topicId}/chat`, { message: trimmed });
  }, [input, isStreaming, topicId, startStream, zoomLevel]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const handleTextareaChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    // Auto-resize
    e.target.style.height = "auto";
    e.target.style.height = `${Math.min(e.target.scrollHeight, 200)}px`;
  };

  if (isLoading) return <LoadingSpinner label="Loading chat history…" />;
  if (error) return <ErrorMessage error={error} />;

  return (
    <div className={styles.container}>
      <div className={styles.messages}>
        {allMessages.length === 0 && !streamingContent && (
          <div className={styles.emptyChat}>
            <span className={styles.emptyIcon}>💬</span>
            <p>Start a conversation about this topic</p>
            <p style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>
              Ask questions, explore ideas, analyze your sources
            </p>
          </div>
        )}

        {allMessages.map((msg) => (
          <div key={msg.id} className={`${styles.message} ${styles[msg.role]}`}>
            {msg.role === "assistant" && (
              <div className={styles.bubbleWrapper}>
                <div
                  className={styles.messageBubble}
                  dangerouslySetInnerHTML={{
                    __html: renderMarkdown(msg.content),
                  }}
                />
                {messageLevels[msg.id] !== undefined && (
                  <span className={styles.zoomBadge} title={`Zoom level ${messageLevels[msg.id]}`}>
                    L{messageLevels[msg.id]}
                  </span>
                )}
                {/* Save to Document button for analytical responses (>150 words) */}
                {countWords(msg.content) >= ANALYTICAL_WORD_THRESHOLD && (
                  <button
                    className={styles.saveToDocBtn}
                    disabled={savedToDocIds.has(msg.id) || savingToDocId === msg.id}
                    onClick={() => {
                      setSavingToDocId(msg.id);
                      addDocumentBlock(topicId, msg.content, "chat")
                        .then(() => {
                          setSavedToDocIds((prev) => new Set([...prev, msg.id]));
                          void queryClient.invalidateQueries({ queryKey: ["document", topicId] });
                        })
                        .catch(console.error)
                        .finally(() => setSavingToDocId(null));
                    }}
                    title="Save this response to the Document tab"
                  >
                    {savedToDocIds.has(msg.id)
                      ? "✅ Saved"
                      : savingToDocId === msg.id
                        ? "⏳…"
                        : "📄 Save to Document"}
                  </button>
                )}
              </div>
            )}
            {msg.role === "user" && (
              <div
                className={styles.messageBubble}
                dangerouslySetInnerHTML={{ __html: msg.content }}
              />
            )}
            <span className={styles.messageTime}>
              {new Date(msg.created_at).toLocaleTimeString(undefined, {
                hour: "2-digit",
                minute: "2-digit",
              })}
            </span>
          </div>
        ))}

        {streamingContent && (
          <div
            className={styles.streamingBubble}
            dangerouslySetInnerHTML={{ __html: renderMarkdown(streamingContent) + '<span class="' + styles.cursor + '"></span>' }}
          />
        )}

        <div ref={messagesEndRef} />
      </div>

      <div className={styles.inputArea}>
        <div className={styles.inputWrapper}>
          <textarea
            className={styles.messageInput}
            value={input}
            onChange={handleTextareaChange}
            onKeyDown={handleKeyDown}
            placeholder="Type a message… (Enter to send, Shift+Enter for newline)"
            disabled={isStreaming}
            rows={1}
          />
        </div>
        {isStreaming ? (
          <button className={styles.stopBtn} onClick={stopStream}>
            ⏹ Stop
          </button>
        ) : (
          <button
            className={styles.sendBtn}
            onClick={sendMessage}
            disabled={!input.trim()}
          >
            Send ↑
          </button>
        )}
      </div>
    </div>
  );
};
