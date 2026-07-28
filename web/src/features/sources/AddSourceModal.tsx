import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { FC } from "react";
import { useEffect, useRef, useState } from "react";
import { addSourceFile, addSourceText, addSourceUrl, getTask } from "../../lib/api";
import styles from "./AddSourceModal.module.css";

type SourceTab = "file" | "url" | "text";

// Poll interval in ms while task is in-flight
const POLL_INTERVAL_MS = 1500;

interface AddSourceModalProps {
  topicId: string;
  onClose: () => void;
  /** Called when the source has been successfully ingested (task done). */
  onSuccess: () => void;
}

export const AddSourceModal: FC<AddSourceModalProps> = ({ topicId, onClose, onSuccess }) => {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<SourceTab>("file");
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");

  // Task polling state — null means no task in flight
  const [pendingTaskId, setPendingTaskId] = useState<string | null>(null);
  const [taskProgress, setTaskProgress] = useState(0);
  // "failed" = task finished with error (show retry UI); "processing" = polling in progress
  const [taskPhase, setTaskPhase] = useState<"idle" | "processing" | "failed">("idle");

  const fileInputRef = useRef<HTMLInputElement>(null);

  // Poll the task endpoint while pendingTaskId is set and task is not terminal
  const { data: taskData } = useQuery({
    queryKey: ["task", pendingTaskId],
    queryFn: () => getTask(pendingTaskId!),
    enabled: pendingTaskId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      // Stop polling once terminal
      if (status === "done" || status === "failed") return false;
      return POLL_INTERVAL_MS;
    },
    staleTime: 0,
  });

  // React to task status changes in an effect (safe side-effect boundary)
  useEffect(() => {
    if (!taskData) return;

    setTaskProgress(taskData.progress);

    if (taskData.status === "done") {
      queryClient.invalidateQueries({ queryKey: ["sources", topicId] });
      onSuccess();
    } else if (taskData.status === "failed") {
      setError(taskData.error ?? "Ingestion failed — please try again");
      setPendingTaskId(null);
      setIsSubmitting(false);
      setTaskPhase("failed");
    }
  }, [taskData, topicId, queryClient, onSuccess]);

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragOver(false);
    const dropped = e.dataTransfer.files[0];
    if (dropped) {
      setFile(dropped);
      if (!name) setName(dropped.name);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files?.[0];
    if (selected) {
      setFile(selected);
      if (!name) setName(selected.name);
    }
  };

  const handleSubmit = async () => {
    setError("");
    setIsSubmitting(true);
    setTaskPhase("idle");

    try {
      let result: { task_id: string };

      if (tab === "file") {
        if (!file) { setError("Please select a file"); setIsSubmitting(false); return; }
        result = await addSourceFile(topicId, file);
      } else if (tab === "url") {
        if (!url.trim()) { setError("Please enter a URL"); setIsSubmitting(false); return; }
        const sourceName = name.trim() || url.trim();
        result = await addSourceUrl(topicId, sourceName, url.trim());
      } else {
        if (!text.trim()) { setError("Please enter some text"); setIsSubmitting(false); return; }
        if (!name.trim()) { setError("Please enter a name"); setIsSubmitting(false); return; }
        result = await addSourceText(topicId, name.trim(), text.trim());
      }

      // Start polling — keep modal open in "processing" state
      setTaskProgress(0);
      setPendingTaskId(result.task_id);
      setTaskPhase("processing");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add source");
      setIsSubmitting(false);
    }
  };

  const handleRetry = () => {
    setPendingTaskId(null);
    setIsSubmitting(false);
    setError("");
    setTaskProgress(0);
    setTaskPhase("idle");
  };

  const isProcessing = taskPhase === "processing";
  const progressPct = Math.round(taskProgress);

  return (
    <div className={styles.overlay} onClick={isProcessing ? undefined : onClose}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div className={styles.header}>
          <h2 className={styles.title}>
            {isProcessing ? "Processing Source…" : "Add Source"}
          </h2>
          {/* Disable close while processing to prevent orphaned state */}
          {!isProcessing && (
            <button className={styles.closeBtn} onClick={onClose}>✕</button>
          )}
        </div>

        {/* ── Processing state ── */}
        {isProcessing ? (
          <div className={styles.processingBody}>
            <div className={styles.processingSpinner} />
            <p className={styles.processingText}>Ingesting source, please wait…</p>
            {taskProgress > 0 && (
              <>
                <div className={styles.progressBar}>
                  <div
                    className={styles.progressFill}
                    style={{ width: `${progressPct}%` }}
                  />
                </div>
                <p className={styles.progressLabel}>{progressPct}%</p>
              </>
            )}
          </div>
        ) : (
          /* ── Normal form + failed state ── */
          <>
            <div className={styles.tabs}>
              {(["file", "url", "text"] as SourceTab[]).map((t) => (
                <button
                  key={t}
                  className={`${styles.tab} ${tab === t ? styles.active : ""}`}
                  onClick={() => setTab(t)}
                  disabled={taskPhase === "failed"}
                >
                  {t === "file" ? "📁 File" : t === "url" ? "🔗 URL" : "📝 Text"}
                </button>
              ))}
            </div>

            <div className={styles.body}>
              {error && <div className={styles.errorMsg}>⚠️ {error}</div>}

              {tab === "file" && (
                <div
                  className={`${styles.fileDropzone} ${isDragOver ? styles.dragOver : ""}`}
                  onDragOver={(e) => { e.preventDefault(); setIsDragOver(true); }}
                  onDragLeave={() => setIsDragOver(false)}
                  onDrop={handleDrop}
                  onClick={() => fileInputRef.current?.click()}
                >
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".pdf,.docx,.xlsx,.txt,.md,.png,.jpg,.jpeg,.webp"
                    onChange={handleFileChange}
                  />
                  {file ? (
                    <>
                      <p>📄 {file.name}</p>
                      <p className={styles.fileSelected}>✅ Ready to upload</p>
                    </>
                  ) : (
                    <>
                      <p>📤 Drop a file here or click to browse</p>
                      <p style={{ fontSize: "0.8rem", marginTop: "0.5rem", color: "var(--text-muted)" }}>
                        PDF, DOCX, XLSX, TXT, MD, Images
                      </p>
                    </>
                  )}
                </div>
              )}

              {tab === "url" && (
                <>
                  <div className={styles.formGroup}>
                    <label className={styles.label}>URL *</label>
                    <input
                      className={styles.input}
                      type="url"
                      placeholder="https://example.com/article"
                      value={url}
                      onChange={(e) => setUrl(e.target.value)}
                    />
                  </div>
                  <div className={styles.formGroup}>
                    <label className={styles.label}>Name (optional)</label>
                    <input
                      className={styles.input}
                      type="text"
                      placeholder="Article title or description"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                    />
                  </div>
                </>
              )}

              {tab === "text" && (
                <>
                  <div className={styles.formGroup}>
                    <label className={styles.label}>Name *</label>
                    <input
                      className={styles.input}
                      type="text"
                      placeholder="Source name or description"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                    />
                  </div>
                  <div className={styles.formGroup}>
                    <label className={styles.label}>Text content *</label>
                    <textarea
                      className={styles.textarea}
                      placeholder="Paste your text content here…"
                      value={text}
                      onChange={(e) => setText(e.target.value)}
                    />
                  </div>
                </>
              )}
            </div>

            <div className={styles.footer}>
              {taskPhase === "failed" ? (
                /* Post-failure: offer retry or close */
                <>
                  <button className="btn btn-secondary" onClick={onClose}>
                    Close
                  </button>
                  <button className="btn btn-primary" onClick={handleRetry}>
                    Try Again
                  </button>
                </>
              ) : (
                <>
                  <button className="btn btn-secondary" onClick={onClose} disabled={isSubmitting}>
                    Cancel
                  </button>
                  <button className="btn btn-primary" onClick={handleSubmit} disabled={isSubmitting}>
                    {isSubmitting ? (
                      <><span className="spinner" style={{ width: 14, height: 14 }} /> Adding…</>
                    ) : (
                      "Add Source"
                    )}
                  </button>
                </>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
};
