import { useQuery } from "@tanstack/react-query";
import { marked } from "marked";
import type { FC } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { ErrorMessage } from "../../components/ErrorMessage";
import { LoadingSpinner } from "../../components/LoadingSpinner";
import { useReadOnly } from "../../hooks/useReadOnly";
import { getDocument, patchDocumentBlock } from "../../lib/api";
import styles from "./DocumentTab.module.css";

// Duration (ms) for the zoom-highlight pulse on a matched block
const BLOCK_HIGHLIGHT_DURATION_MS = 4000;

marked.setOptions({ breaks: true });

interface DocumentTabProps {
  topicId: string;
  /** Called when the user taps the 💬 button on a block to ask about it in Chat */
  onBlockTap?: (blockContent: string) => void;
  /** Block ID to scroll to and highlight (set by Map zoom). Cleared via onHighlightConsumed. */
  highlightedDocBlockId?: string | null;
  onHighlightConsumed?: () => void;
}

type ViewMode = "split" | "edit" | "preview";

const AUTOSAVE_DELAY_MS = 2000;

export const DocumentTab: FC<DocumentTabProps> = ({
  topicId,
  onBlockTap,
  highlightedDocBlockId,
  onHighlightConsumed,
}) => {
  const readOnly = useReadOnly();
  const [viewMode, setViewMode] = useState<ViewMode>("split");
  const [blockContents, setBlockContents] = useState<Record<string, string>>({});
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  // Block ID currently showing the zoom-highlight pulse
  const [pulsedBlockId, setPulsedBlockId] = useState<string | null>(null);
  const debounceTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  const blockRefs = useRef<Record<string, HTMLDivElement | null>>({});

  const { data: doc, isLoading, error } = useQuery({
    queryKey: ["document", topicId],
    queryFn: () => getDocument(topicId),
    staleTime: 30_000,
  });

  // Force out of "edit" mode when the server is read-only — editing is disabled
  useEffect(() => {
    if (readOnly) setViewMode((m) => (m === "edit" ? "preview" : m));
  }, [readOnly]);

  // Sync server data into local edit state
  useEffect(() => {
    if (!doc) return;
    setBlockContents((prev) => {
      const next = { ...prev };
      for (const block of doc.blocks) {
        if (!(block.id in next)) {
          next[block.id] = block.content_md;
        }
      }
      return next;
    });
  }, [doc]);

  // Scroll to and pulse-highlight the block set by Map zoom
  useEffect(() => {
    if (!highlightedDocBlockId) return;

    // Notify parent so it clears the value (one-shot)
    onHighlightConsumed?.();

    setPulsedBlockId(highlightedDocBlockId);

    // Scroll the block into view — defer one frame so the DOM is ready
    requestAnimationFrame(() => {
      const el = blockRefs.current[highlightedDocBlockId];
      el?.scrollIntoView({ behavior: "smooth", block: "center" });
    });

    // Auto-remove pulse after duration
    const timer = setTimeout(() => setPulsedBlockId(null), BLOCK_HIGHLIGHT_DURATION_MS);
    return () => clearTimeout(timer);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [highlightedDocBlockId]);

  const saveBlock = useCallback(
    async (blockId: string, content: string) => {
      setSaveStatus("saving");
      try {
        await patchDocumentBlock(topicId, blockId, content);
        setSaveStatus("saved");
        setTimeout(() => setSaveStatus("idle"), 2000);
      } catch {
        setSaveStatus("error");
      }
    },
    [topicId],
  );

  const handleBlockChange = useCallback(
    (blockId: string, content: string) => {
      if (readOnly) return;
      setBlockContents((prev) => ({ ...prev, [blockId]: content }));

      // Debounce autosave
      if (debounceTimers.current[blockId]) {
        clearTimeout(debounceTimers.current[blockId]);
      }
      debounceTimers.current[blockId] = setTimeout(() => {
        void saveBlock(blockId, content);
      }, AUTOSAVE_DELAY_MS);
    },
    [readOnly, saveBlock],
  );

  if (isLoading) return <LoadingSpinner label="Loading document…" />;
  if (error) return <ErrorMessage error={error} />;

  const blocks = doc?.blocks ?? [];
  const isEmpty = blocks.length === 0;

  const renderPreview = (blockId: string) => {
    const content = blockContents[blockId] ?? "";
    try {
      return marked.parse(content) as string;
    } catch {
      return content;
    }
  };

  return (
    <div className={styles.container}>
      <div className={styles.toolbar}>
        <div className={styles.modeToggle}>
          {(readOnly ? (["split", "preview"] as ViewMode[]) : (["edit", "split", "preview"] as ViewMode[])).map((m) => (
            <button
              key={m}
              className={`${styles.modeBtn} ${viewMode === m ? styles.active : ""}`}
              onClick={() => setViewMode(m)}
            >
              {m === "edit" ? "✏️ Edit" : m === "split" ? "⊞ Split" : "👁 Preview"}
            </button>
          ))}
        </div>

        <span
          className={`${styles.saveStatus} ${
            saveStatus === "saving" ? styles.saving : saveStatus === "saved" ? styles.saved : ""
          }`}
        >
          {saveStatus === "saving" && "⏳ Saving…"}
          {saveStatus === "saved" && "✅ Saved"}
          {saveStatus === "error" && "❌ Save failed"}
        </span>
      </div>

      {isEmpty ? (
        <div className={styles.emptyDoc}>
          <span style={{ fontSize: "2.5rem" }}>📄</span>
          <p>No document yet</p>
          <p style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>
            Run analysis to generate the document from your sources
          </p>
        </div>
      ) : (
        <div className={styles.editorArea}>
          {(viewMode === "edit" || viewMode === "split") && (
            <div className={styles.editorPane}>
              <div className={styles.blockEditor}>
                {blocks.map((block, idx) => (
                  <div
                    key={block.id}
                    className={`${styles.block} ${pulsedBlockId === block.id ? styles.blockPulse : ""}`}
                    ref={(el) => { blockRefs.current[block.id] = el; }}
                  >
                    <div className={styles.blockHeader}>
                      <label className={styles.blockLabel} htmlFor={`block-${block.id}`}>
                        Block {idx + 1}
                      </label>
                      {onBlockTap && !readOnly && (
                        <button
                          className={styles.blockAskBtn}
                          title="Ask Chat about this block"
                          onClick={() => onBlockTap(blockContents[block.id] ?? block.content_md)}
                        >
                          💬
                        </button>
                      )}
                    </div>
                    <textarea
                      id={`block-${block.id}`}
                      className={styles.blockTextarea}
                      value={blockContents[block.id] ?? block.content_md}
                      onChange={(e) => handleBlockChange(block.id, e.target.value)}
                      placeholder="Enter markdown content…"
                      readOnly={readOnly}
                    />
                  </div>
                ))}
              </div>
            </div>
          )}

          {(viewMode === "preview" || viewMode === "split") && (
            <div className={styles.previewPane}>
              <div className={styles.previewContent}>
                {blocks.map((block) => (
                  <div
                    key={block.id}
                    className={`${styles.previewBlock} markdown-body ${pulsedBlockId === block.id ? styles.blockPulse : ""}`}
                    ref={(el) => { blockRefs.current[block.id] = el; }}
                  >
                    {onBlockTap && !readOnly && (
                      <button
                        className={styles.blockAskBtnPreview}
                        title="Ask Chat about this block"
                        onClick={() => onBlockTap(blockContents[block.id] ?? block.content_md)}
                      >
                        💬 Ask
                      </button>
                    )}
                    <div dangerouslySetInnerHTML={{ __html: renderPreview(block.id) }} />
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
