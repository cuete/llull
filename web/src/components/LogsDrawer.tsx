import type { FC } from "react";
import { useState } from "react";
import { LogsTab } from "../features/logs/LogsTab";
import { useLogsStore } from "../stores/logsStore";
import styles from "./LogsDrawer.module.css";

export const LogsDrawer: FC = () => {
  const [open, setOpen] = useState(false);

  const errorCount = useLogsStore((s) => {
    const consoleErrors = s.consoleLogs.filter((e) => e.level === "error").length;
    const apiErrors = s.apiLogs.filter(
      (e) => e.statusCategory === "4xx" || e.statusCategory === "5xx",
    ).length;
    return consoleErrors + apiErrors;
  });

  return (
    <>
      {/* Floating trigger button */}
      <button
        className={styles.fab}
        onClick={() => setOpen((prev) => !prev)}
        aria-label={open ? "Close logs" : "Open logs"}
        title={open ? "Close logs" : "Open logs"}
      >
        🪲
        {errorCount > 0 && (
          <span className={styles.errorBadge} aria-label={`${errorCount} errors`}>
            {errorCount > 99 ? "99+" : errorCount}
          </span>
        )}
      </button>

      {/* Drawer overlay */}
      {open && (
        <div className={styles.drawer} role="dialog" aria-label="Debug logs">
          <div className={styles.drawerHeader}>
            <span className={styles.drawerTitle}>🪲 Debug Logs</span>
            <button
              className={styles.closeBtn}
              onClick={() => setOpen(false)}
              aria-label="Close logs drawer"
            >
              ✕
            </button>
          </div>
          <div className={styles.drawerBody}>
            <LogsTab />
          </div>
        </div>
      )}
    </>
  );
};
