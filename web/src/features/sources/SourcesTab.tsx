import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { FC } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { ErrorMessage } from "../../components/ErrorMessage";
import { LoadingSpinner } from "../../components/LoadingSpinner";
import { deleteSource, factCheckSource, getTask, listSources } from "../../lib/api";
import type { FactCheckClaim, Source } from "../../lib/types";
import { AddSourceModal } from "./AddSourceModal";
import { SourceDetailModal } from "./SourceDetailModal";
import styles from "./SourcesTab.module.css";

interface SourcesTabProps {
  topicId: string;
}

const SOURCE_ICONS: Record<string, string> = {
  pdf: "📕",
  docx: "📘",
  xlsx: "📗",
  text: "📝",
  url: "🔗",
  image: "🖼️",
};

function getSourceIcon(type: string): string {
  return SOURCE_ICONS[type] ?? "📄";
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

// ─── Rating badge helpers ────────────────────────────────────────────────────

function aiSuspicionColor(score: number): string {
  if (score < 30) return "var(--success, #22c55e)";
  if (score <= 70) return "var(--warning, #f59e0b)";
  return "var(--danger, #ef4444)";
}

function qualityColor(score: number): string {
  if (score < 40) return "var(--danger, #ef4444)";
  if (score <= 70) return "var(--warning, #f59e0b)";
  return "var(--success, #22c55e)";
}

function verdictIcon(verdict: string): string {
  if (verdict === "verified") return "✅";
  if (verdict === "contradicted") return "❌";
  return "⚠️";
}

interface RatingBadgesProps {
  source: Source;
  topicId: string;
  onFactCheckDone: (sourceId: string, updated: Source) => void;
}

const RatingBadges: FC<RatingBadgesProps> = ({ source, topicId, onFactCheckDone }) => {
  const queryClient = useQueryClient();
  const [fcLoading, setFcLoading] = useState(false);
  const [claimsExpanded, setClaimsExpanded] = useState(false);
  const [tooltip, setTooltip] = useState<{ id: string; text: string } | null>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);

  const claims: FactCheckClaim[] = (() => {
    if (!source.fact_check_result) return [];
    try { return JSON.parse(source.fact_check_result) as FactCheckClaim[]; } catch { return []; }
  })();

  const handleFactCheck = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (fcLoading) return;
    setFcLoading(true);
    try {
      const result = await factCheckSource(topicId, source.id);
      const updatedSource = {
        ...source,
        fact_check_score: result.fact_check_score,
        fact_check_result: JSON.stringify(result.claims),
        quality_score: result.quality_score_updated ?? source.quality_score,
      };
      onFactCheckDone(source.id, updatedSource);
      queryClient.invalidateQueries({ queryKey: ["sources", topicId] });
    } catch {
      // silent fail — user can retry
    } finally {
      setFcLoading(false);
    }
  };

  const showTooltip = (id: string, text: string) => setTooltip({ id, text });
  const hideTooltip = () => setTooltip(null);

  const hasFc = source.fact_check_score != null;

  return (
    <div className={styles.ratingRow} onClick={(e) => e.stopPropagation()}>
      {/* AI Suspicion badge */}
      <span
        className={styles.ratingBadge}
        style={{ color: source.ai_suspicion != null ? aiSuspicionColor(source.ai_suspicion) : undefined }}
        onMouseEnter={() => source.ai_suspicion_reason && showTooltip(`ai-${source.id}`, source.ai_suspicion_reason)}
        onMouseLeave={hideTooltip}
        title={source.ai_suspicion_reason ?? undefined}
      >
        🤖 AI: {source.ai_suspicion != null ? `${source.ai_suspicion}%` : "–"}
      </span>

      {/* Quality badge */}
      <span
        className={styles.ratingBadge}
        style={{ color: source.quality_score != null ? qualityColor(source.quality_score) : undefined }}
        onMouseEnter={() => source.quality_reason && showTooltip(`q-${source.id}`, source.quality_reason)}
        onMouseLeave={hideTooltip}
        title={source.quality_reason ?? undefined}
      >
        ⭐ Quality: {source.quality_score != null ? `${source.quality_score}%` : "–"}
      </span>

      {/* Fact-check button / result */}
      {hasFc ? (
        <button
          className={`${styles.ratingBadge} ${styles.ratingBadgeBtn}`}
          onClick={(e) => { e.stopPropagation(); setClaimsExpanded((v) => !v); }}
          title="Toggle claims"
        >
          ✅ FC: {source.fact_check_score}%
        </button>
      ) : (
        <button
          className={`${styles.ratingBadge} ${styles.ratingBadgeBtn}`}
          onClick={handleFactCheck}
          disabled={fcLoading}
          title="Run fact-check"
        >
          {fcLoading ? "⏳ Checking…" : "🔍 Fact Check"}
        </button>
      )}

      {/* Tooltip */}
      {tooltip && (
        <div ref={tooltipRef} className={styles.ratingTooltip}>
          {tooltip.text}
        </div>
      )}

      {/* Claims list (expanded) */}
      {claimsExpanded && claims.length > 0 && (
        <div className={styles.claimsList}>
          {claims.map((c, i) => (
            <div key={i} className={styles.claimItem}>
              <span className={styles.claimVerdict}>{verdictIcon(c.verdict)}</span>
              <div className={styles.claimBody}>
                <div className={styles.claimText}>{c.claim}</div>
                <div className={styles.claimEvidence}>{c.evidence}</div>
                {c.source_url && (
                  <a href={c.source_url} target="_blank" rel="noopener noreferrer" className={styles.claimLink}>
                    {c.source_url.slice(0, 60)}{c.source_url.length > 60 ? "…" : ""}
                  </a>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

// ─── Pending task tracker ────────────────────────────────────────────────────

interface PendingTask {
  taskId: string;
  /** Display label shown in the placeholder card */
  label: string;
  /** Source type hint for the icon (url / text / file) */
  sourceType: string;
}

interface PendingCardProps {
  topicId: string;
  task: PendingTask;
  onDone: (taskId: string) => void;
  onFailed: (taskId: string, errorMsg: string) => void;
  onDismiss: (taskId: string) => void;
}

// Poll interval in ms
const POLL_INTERVAL_MS = 1500;

/**
 * Renders a single in-flight or failed source placeholder.
 * Handles its own polling via useQuery, uses useEffect for transitions.
 */
const PendingCard: FC<PendingCardProps> = ({ topicId, task, onDone, onFailed, onDismiss }) => {
  const queryClient = useQueryClient();
  const [isFailed, setIsFailed] = useState(false);
  const [failError, setFailError] = useState("");

  const { data: taskData } = useQuery({
    queryKey: ["task", task.taskId],
    queryFn: () => getTask(task.taskId),
    enabled: !isFailed,
    staleTime: 0,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status === "done" || status === "failed") return false;
      return POLL_INTERVAL_MS;
    },
  });

  useEffect(() => {
    if (!taskData) return;

    if (taskData.status === "done") {
      queryClient.invalidateQueries({ queryKey: ["sources", topicId] });
      onDone(task.taskId);
    } else if (taskData.status === "failed") {
      const msg = taskData.error ?? "Ingestion failed";
      setIsFailed(true);
      setFailError(msg);
      onFailed(task.taskId, msg);
    }
  }, [taskData, task.taskId, topicId, queryClient, onDone, onFailed]);

  if (isFailed) {
    return (
      <div className={`${styles.sourceCard} ${styles.pendingCardFailed}`}>
        <span className={styles.sourceIcon}>❌</span>
        <div className={styles.sourceInfo}>
          <div className={styles.sourceName}>{task.label}</div>
          <div className={styles.sourceMeta}>Failed — {failError}</div>
        </div>
        <div className={styles.sourceActions}>
          <button
            className={styles.deleteBtn}
            onClick={() => onDismiss(task.taskId)}
            title="Dismiss"
          >
            ✕
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className={`${styles.sourceCard} ${styles.pendingCard}`}>
      <span className={`${styles.sourceIcon} ${styles.pendingSpinner}`}>⏳</span>
      <div className={styles.sourceInfo}>
        <div className={styles.sourceName}>{task.label}</div>
        <div className={styles.sourceMeta}>Processing…</div>
      </div>
    </div>
  );
};

// ─── Main Tab ────────────────────────────────────────────────────────────────

export const SourcesTab: FC<SourcesTabProps> = ({ topicId }) => {
  const queryClient = useQueryClient();
  const [showAddModal, setShowAddModal] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Source | null>(null);
  const [pendingTasks, setPendingTasks] = useState<PendingTask[]>([]);
  const [expandedSource, setExpandedSource] = useState<Source | null>(null);
  // Local overrides for fact-check results (avoids full refetch lag)
  const [sourceOverrides, setSourceOverrides] = useState<Record<string, Source>>({});

  const { data: sources, isLoading, error } = useQuery({
    queryKey: ["sources", topicId],
    queryFn: () => listSources(topicId),
    staleTime: 30_000,
  });

  const deleteMutation = useMutation({
    mutationFn: (sid: string) => deleteSource(topicId, sid),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sources", topicId] });
      setDeleteTarget(null);
    },
  });

  // Called by AddSourceModal when ingestion completes (modal closes itself via this callback)
  const handleAddSuccess = useCallback(() => {
    setShowAddModal(false);
    queryClient.invalidateQueries({ queryKey: ["sources", topicId] });
  }, [topicId, queryClient]);

  const handleTaskDone = useCallback((taskId: string) => {
    setPendingTasks((prev) => prev.filter((t) => t.taskId !== taskId));
    queryClient.invalidateQueries({ queryKey: ["sources", topicId] });
  }, [topicId, queryClient]);

  const handleTaskFailed = useCallback((_taskId: string, _errorMsg: string) => {
    // Card switches to failed UI on its own; SourcesTab just keeps it visible until dismissed
  }, []);

  const handleTaskDismiss = useCallback((taskId: string) => {
    setPendingTasks((prev) => prev.filter((t) => t.taskId !== taskId));
  }, []);

  const handleFactCheckDone = useCallback((sourceId: string, updated: Source) => {
    setSourceOverrides((prev) => ({ ...prev, [sourceId]: updated }));
  }, []);

  const formatDate = (iso: string) =>
    new Date(iso).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
    });

  if (isLoading) return <LoadingSpinner label="Loading sources…" />;
  if (error) return <ErrorMessage error={error} />;

  const totalCount = (sources?.length ?? 0) + pendingTasks.length;
  const hasContent = totalCount > 0;

  return (
    <div className={styles.container}>
      <div className={styles.toolbar}>
        <span className={styles.toolbarTitle}>
          {totalCount} source{totalCount !== 1 ? "s" : ""}
        </span>
        <button className="btn btn-primary" onClick={() => setShowAddModal(true)}>
          + Add Source
        </button>
      </div>

      {!hasContent ? (
        <div className={styles.emptyState}>
          <span className={styles.emptyIcon}>📁</span>
          <p>No sources yet</p>
          <p style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>
            Add PDFs, web pages, or text to build your knowledge base
          </p>
          <button
            className="btn btn-primary"
            style={{ marginTop: "0.5rem" }}
            onClick={() => setShowAddModal(true)}
          >
            + Add First Source
          </button>
        </div>
      ) : (
        <div className={styles.sourceList}>
          {/* Pending placeholder cards (in-flight or failed) */}
          {pendingTasks.map((task) => (
            <PendingCard
              key={task.taskId}
              topicId={topicId}
              task={task}
              onDone={handleTaskDone}
              onFailed={handleTaskFailed}
              onDismiss={handleTaskDismiss}
            />
          ))}

          {/* Committed source cards */}
          {sources?.map((rawSource) => {
            const source = sourceOverrides[rawSource.id] ?? rawSource;
            return (
              <div
                key={source.id}
                className={styles.sourceCard}
                style={{ cursor: "pointer" }}
                onClick={() => setExpandedSource(source)}
              >
                <span className={styles.sourceIcon}>{getSourceIcon(source.type)}</span>
                <div className={styles.sourceInfo}>
                  <div className={styles.sourceName}>{source.name}</div>
                  <div className={styles.sourceMeta}>
                    {source.type.toUpperCase()} · {formatDate(source.created_at)}
                    {source.extracted_text && (
                      <> · {formatBytes(source.extracted_text.length)} text</>
                    )}
                  </div>
                  <RatingBadges
                    source={source}
                    topicId={topicId}
                    onFactCheckDone={handleFactCheckDone}
                  />
                </div>
                <div className={styles.sourceActions}>
                  <button
                    className={styles.deleteBtn}
                    onClick={(e) => {
                      e.stopPropagation();
                      setDeleteTarget(source);
                    }}
                    title="Delete source"
                  >
                    🗑️
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {showAddModal && (
        <AddSourceModal
          topicId={topicId}
          onClose={() => setShowAddModal(false)}
          onSuccess={handleAddSuccess}
        />
      )}

      {deleteTarget && (
        <ConfirmDialog
          title="Delete Source"
          message={`Are you sure you want to delete "${deleteTarget.name}"?`}
          confirmLabel="Delete"
          danger
          onConfirm={() => deleteMutation.mutate(deleteTarget.id)}
          onCancel={() => setDeleteTarget(null)}
        />
      )}

      {expandedSource && (
        <SourceDetailModal
          source={expandedSource}
          onClose={() => setExpandedSource(null)}
        />
      )}
    </div>
  );
};
