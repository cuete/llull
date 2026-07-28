import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { FC } from "react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { ErrorMessage } from "../../components/ErrorMessage";
import { LoadingSpinner } from "../../components/LoadingSpinner";
import { useReadOnly } from "../../hooks/useReadOnly";
import { createTopic, deleteTopic, listTopics } from "../../lib/api";
import type { Topic } from "../../lib/types";
import styles from "./TopicList.module.css";

export const TopicList: FC = () => {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const readOnly = useReadOnly();
  const [newTitle, setNewTitle] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<Topic | null>(null);

  const { data: topics, isLoading, error } = useQuery({
    queryKey: ["topics"],
    queryFn: listTopics,
    staleTime: 30_000,
  });

  const createMutation = useMutation({
    mutationFn: (title: string) => createTopic(title),
    onSuccess: (topic) => {
      queryClient.invalidateQueries({ queryKey: ["topics"] });
      setNewTitle("");
      navigate(`/topics/${topic.id}`);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteTopic(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["topics"] });
      setDeleteTarget(null);
    },
  });

  const handleCreate = () => {
    const trimmed = newTitle.trim();
    if (!trimmed) return;
    createMutation.mutate(trimmed);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") handleCreate();
  };

  const formatDate = (iso: string) =>
    new Date(iso).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
    });

  return (
    <div className={styles.page}>
      <div className={styles.pageHeader}>
        <div>
          <h1 className={styles.title}>Topics</h1>
          <p className={styles.subtitle}>Organize your research and knowledge</p>
        </div>
      </div>

      {!readOnly && (
        <div className={styles.createForm}>
          <input
            className={styles.createInput}
            type="text"
            placeholder="New topic title…"
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={createMutation.isPending}
          />
          <button
            className="btn btn-primary"
            onClick={handleCreate}
            disabled={!newTitle.trim() || createMutation.isPending}
          >
            {createMutation.isPending ? (
              <><span className="spinner" style={{ width: 14, height: 14 }} /> Creating…</>
            ) : (
              "+ New Topic"
            )}
          </button>
        </div>
      )}

      {createMutation.error && (
        <div style={{ marginBottom: "1rem" }}>
          <ErrorMessage error={createMutation.error} />
        </div>
      )}

      {isLoading && <LoadingSpinner label="Loading topics…" />}
      {error && <ErrorMessage error={error} />}

      {!isLoading && !error && topics && (
        <>
          {topics.length === 0 ? (
            <div className={styles.emptyState}>
              <div className={styles.emptyIcon}>📚</div>
              <p className={styles.emptyText}>No topics yet</p>
              <p className={styles.emptyHint}>Create your first topic above to get started</p>
            </div>
          ) : (
            <div className={styles.topicGrid}>
              {topics.map((topic) => (
                <div
                  key={topic.id}
                  className={styles.topicCard}
                  onClick={() => navigate(`/topics/${topic.id}`)}
                >
                  <div className={styles.topicInfo}>
                    <div className={styles.topicTitle}>{topic.title}</div>
                    <div className={styles.topicMeta}>
                      Created {formatDate(topic.created_at)} · Updated {formatDate(topic.updated_at)}
                    </div>
                  </div>
                  {!readOnly && (
                    <div className={styles.topicActions}>
                      <button
                        className={styles.deleteBtn}
                        onClick={(e) => {
                          e.stopPropagation();
                          setDeleteTarget(topic);
                        }}
                        title="Delete topic"
                      >
                        🗑️
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {deleteTarget && (
        <ConfirmDialog
          title="Delete Topic"
          message={`Are you sure you want to delete "${deleteTarget.title}"? This action cannot be undone.`}
          confirmLabel="Delete"
          danger
          onConfirm={() => deleteMutation.mutate(deleteTarget.id)}
          onCancel={() => setDeleteTarget(null)}
        />
      )}
    </div>
  );
};
