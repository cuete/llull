import { create } from "zustand";

const MAX_ENTRIES = 200;

export type ConsoleLevel = "log" | "warn" | "error";

export interface ConsoleLogEntry {
  id: string;
  level: ConsoleLevel;
  message: string;
  timestamp: number;
}

export type ApiLogStatus = "pending" | "2xx" | "4xx" | "5xx";

export interface ApiLogEntry {
  id: string;
  method: string;
  url: string;
  status: number | null;
  duration: number | null;
  statusCategory: ApiLogStatus;
  timestamp: number;
}

interface LogsState {
  consoleLogs: ConsoleLogEntry[];
  apiLogs: ApiLogEntry[];
  addConsoleLog: (entry: Omit<ConsoleLogEntry, "id">) => void;
  clearConsoleLogs: () => void;
  addApiLog: (entry: Omit<ApiLogEntry, "id">) => void;
  updateApiLog: (id: string, update: Partial<ApiLogEntry>) => void;
  clearApiLogs: () => void;
}

export const useLogsStore = create<LogsState>((set) => ({
  consoleLogs: [],
  apiLogs: [],

  addConsoleLog: (entry) =>
    set((state) => {
      const newEntry: ConsoleLogEntry = { ...entry, id: `c-${Date.now()}-${Math.random()}` };
      const updated = [newEntry, ...state.consoleLogs];
      return { consoleLogs: updated.slice(0, MAX_ENTRIES) };
    }),

  clearConsoleLogs: () => set({ consoleLogs: [] }),

  addApiLog: (entry) =>
    set((state) => {
      const newEntry: ApiLogEntry = { ...entry, id: `a-${Date.now()}-${Math.random()}` };
      const updated = [newEntry, ...state.apiLogs];
      return { apiLogs: updated.slice(0, MAX_ENTRIES) };
    }),

  updateApiLog: (id, update) =>
    set((state) => ({
      apiLogs: state.apiLogs.map((e) => (e.id === id ? { ...e, ...update } : e)),
    })),

  clearApiLogs: () => set({ apiLogs: [] }),
}));
