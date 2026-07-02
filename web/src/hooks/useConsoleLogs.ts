import { useEffect } from "react";
import { useLogsStore } from "../stores/logsStore";
import type { ConsoleLevel } from "../stores/logsStore";

type ConsoleFn = (...args: unknown[]) => void;

interface OriginalConsoleMethods {
  log: ConsoleFn;
  warn: ConsoleFn;
  error: ConsoleFn;
}

// Stored outside hook so monkey-patch survives re-renders
let patched = false;
const originals: OriginalConsoleMethods = {
  log: console.log.bind(console),
  warn: console.warn.bind(console),
  error: console.error.bind(console),
};

function formatArgs(args: unknown[]): string {
  return args
    .map((a) => {
      if (typeof a === "string") return a;
      try {
        return JSON.stringify(a, null, 0);
      } catch {
        return String(a);
      }
    })
    .join(" ");
}

function patchConsole(addLog: (level: ConsoleLevel, message: string, ts: number) => void): void {
  if (patched) return;
  patched = true;

  const levels: ConsoleLevel[] = ["log", "warn", "error"];
  for (const level of levels) {
    console[level] = (...args: unknown[]) => {
      originals[level](...args);
      addLog(level, formatArgs(args), Date.now());
    };
  }
}

/**
 * Initialize console monkey-patching once at app level.
 * Safe to call multiple times — only patches once.
 */
export function useConsoleLogs(): void {
  const addConsoleLog = useLogsStore((s) => s.addConsoleLog);

  useEffect(() => {
    patchConsole((level, message, timestamp) => {
      addConsoleLog({ level, message, timestamp });
    });

    // No cleanup — we keep the patch for the app lifetime
  }, [addConsoleLog]);
}
