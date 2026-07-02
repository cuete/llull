import type { FC } from "react";
import { useState } from "react";
import type { Source } from "../../lib/types";
import styles from "./SourceDetailModal.module.css";

interface SourceDetailModalProps {
  source: Source;
  onClose: () => void;
}

const TYPE_BADGE_MAP: Record<string, string> = {
  url: "URL",
  pdf: "PDF",
  docx: "DOCX",
  xlsx: "XLSX",
  text: "TEXT",
  image: "IMAGE",
};

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

export const SourceDetailModal: FC<SourceDetailModalProps> = ({ source, onClose }) => {
  const [previewExpanded, setPreviewExpanded] = useState(false);

  const typeBadge = TYPE_BADGE_MAP[source.type] ?? source.type.toUpperCase();
  const previewText = source.extracted_text
    ? previewExpanded
      ? source.extracted_text
      : source.extracted_text.slice(0, 500) + (source.extracted_text.length > 500 ? "…" : "")
    : null;

  return (
    <div className={styles.overlay} onClick={onClose} role="dialog" aria-modal="true">
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className={styles.header}>
          <div className={styles.headerLeft}>
            <span className={styles.name}>{source.name}</span>
            <span className={styles.typeBadge}>{typeBadge}</span>
          </div>
          <button className={styles.closeBtn} onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>

        {/* Body */}
        <div className={styles.body}>
          {/* URL row */}
          {source.source_url && (
            <div className={styles.row}>
              <span className={styles.label}>Link</span>
              <div className={styles.linkRow}>
                <a
                  href={source.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={styles.link}
                >
                  {source.source_url}
                </a>
                <a
                  href={source.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="btn btn-secondary"
                  style={{ fontSize: "0.8rem", padding: "0.25rem 0.625rem" }}
                >
                  Open ↗
                </a>
              </div>
            </div>
          )}

          {/* Date */}
          <div className={styles.row}>
            <span className={styles.label}>Added</span>
            <span className={styles.value}>{formatDate(source.created_at)}</span>
          </div>

          {/* Extracted text preview */}
          {previewText !== null && (
            <div className={styles.previewSection}>
              <div className={styles.previewHeader}>
                <span className={styles.label}>Extracted text</span>
                {source.extracted_text && source.extracted_text.length > 500 && (
                  <button
                    className={styles.expandBtn}
                    onClick={() => setPreviewExpanded((v) => !v)}
                  >
                    {previewExpanded ? "Collapse" : "Show all"}
                  </button>
                )}
              </div>
              <pre className={styles.preview}>{previewText}</pre>
            </div>
          )}

          {!previewText && (
            <div className={styles.row}>
              <span className={styles.value} style={{ color: "var(--text-muted)" }}>
                No extracted text available
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
