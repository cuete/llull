import type { FC } from "react";
import { useLogsStore } from "../../stores/logsStore";
import type { ApiLogEntry, ConsoleLogEntry } from "../../stores/logsStore";
import styles from "./LogsTab.module.css";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatTime(ts: number): string {
  const d = new Date(ts);
  const hh = d.getHours().toString().padStart(2, "0");
  const mm = d.getMinutes().toString().padStart(2, "0");
  const ss = d.getSeconds().toString().padStart(2, "0");
  const ms = d.getMilliseconds().toString().padStart(3, "0");
  return `${hh}:${mm}:${ss}.${ms}`;
}

// ─── Console Panel ────────────────────────────────────────────────────────────

function consoleLevelClass(level: ConsoleLogEntry["level"]): string {
  switch (level) {
    case "warn":
      return styles.levelWarn ?? "";
    case "error":
      return styles.levelError ?? "";
    default:
      return styles.levelLog ?? "";
  }
}

interface ConsolePanelProps {
  entries: ConsoleLogEntry[];
  onClear: () => void;
}

const ConsolePanel: FC<ConsolePanelProps> = ({ entries, onClear }) => {
  const errorCount = entries.filter((e) => e.level === "error").length;

  return (
    <div className={styles.panel}>
      <div className={styles.panelHeader}>
        <span className={styles.panelTitle}>
          UI Logs
          {errorCount > 0 && <span className={styles.badge}>{errorCount}</span>}
        </span>
        <button className={styles.clearBtn} onClick={onClear}>
          Clear
        </button>
      </div>
      <div className={styles.logList}>
        {entries.length === 0 ? (
          <div className={styles.emptyState}>No logs yet</div>
        ) : (
          entries.map((entry) => (
            <div
              key={entry.id}
              className={`${styles.entry} ${consoleLevelClass(entry.level)}`}
            >
              <span className={styles.timestamp}>{formatTime(entry.timestamp)}</span>
              <span>{entry.message}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
};

// ─── API Panel ────────────────────────────────────────────────────────────────

function apiStatusClass(entry: ApiLogEntry): string {
  switch (entry.statusCategory) {
    case "2xx":
      return styles.status2xx ?? "";
    case "4xx":
      return styles.status4xx ?? "";
    case "5xx":
      return styles.status5xx ?? "";
    default:
      return styles.statusPending ?? "";
  }
}

interface ApiPanelProps {
  entries: ApiLogEntry[];
  onClear: () => void;
}

const ApiPanel: FC<ApiPanelProps> = ({ entries, onClear }) => {
  const errorCount = entries.filter(
    (e) => e.statusCategory === "4xx" || e.statusCategory === "5xx",
  ).length;

  return (
    <div className={styles.panel}>
      <div className={styles.panelHeader}>
        <span className={styles.panelTitle}>
          API Logs
          {errorCount > 0 && <span className={styles.badge}>{errorCount}</span>}
        </span>
        <button className={styles.clearBtn} onClick={onClear}>
          Clear
        </button>
      </div>
      <div className={styles.logList}>
        {entries.length === 0 ? (
          <div className={styles.emptyState}>No requests yet</div>
        ) : (
          entries.map((entry) => (
            <div
              key={entry.id}
              className={`${styles.entry} ${apiStatusClass(entry)}`}
            >
              <span className={styles.timestamp}>{formatTime(entry.timestamp)}</span>
              <span>
                <span className={styles.apiMethod}>{entry.method}</span>
                {entry.status !== null && (
                  <span className={styles.apiStatus}>
                    {entry.status === 0 ? "ERR" : entry.status}
                  </span>
                )}
                {entry.duration !== null && (
                  <span className={styles.apiDuration}>{entry.duration}ms</span>
                )}
                <span className={styles.apiUrl}>{entry.url}</span>
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  );
};

// ─── LogsTab ─────────────────────────────────────────────────────────────────

export const LogsTab: FC = () => {
  const consoleLogs = useLogsStore((s) => s.consoleLogs);
  const apiLogs = useLogsStore((s) => s.apiLogs);
  const clearConsoleLogs = useLogsStore((s) => s.clearConsoleLogs);
  const clearApiLogs = useLogsStore((s) => s.clearApiLogs);

  return (
    <div className={styles.container}>
      <ConsolePanel entries={consoleLogs} onClear={clearConsoleLogs} />
      <ApiPanel entries={apiLogs} onClear={clearApiLogs} />
    </div>
  );
};
