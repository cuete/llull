import { useLogsStore } from "../stores/logsStore";
import type { ApiLogStatus } from "../stores/logsStore";

function statusCategory(status: number): ApiLogStatus {
  if (status >= 200 && status < 300) return "2xx";
  if (status >= 400 && status < 500) return "4xx";
  if (status >= 500) return "5xx";
  return "pending";
}

let initialized = false;

/**
 * Wraps window.fetch to log all requests/responses to the logsStore.
 * Call once at app startup (main.tsx).
 */
export function initApiFetchLogger(): void {
  if (initialized) return;
  initialized = true;

  const originalFetch = window.fetch.bind(window);

  window.fetch = async (
    input: RequestInfo | URL,
    init?: RequestInit,
  ): Promise<Response> => {
    const { addApiLog, updateApiLog } = useLogsStore.getState();

    const method = init?.method?.toUpperCase() ?? "GET";
    const url = typeof input === "string"
      ? input
      : input instanceof URL
        ? input.toString()
        : input.url;

    const timestamp = Date.now();

    // Add pending entry
    addApiLog({
      method,
      url,
      status: null,
      duration: null,
      statusCategory: "pending",
      timestamp,
    });

    // Get the id of the entry just added (it's always first in the array)
    const entryId = useLogsStore.getState().apiLogs[0]?.id ?? "";

    try {
      const response = await originalFetch(input, init);
      const duration = Date.now() - timestamp;

      updateApiLog(entryId, {
        status: response.status,
        duration,
        statusCategory: statusCategory(response.status),
      });

      return response;
    } catch (err) {
      const duration = Date.now() - timestamp;
      updateApiLog(entryId, {
        status: 0,
        duration,
        statusCategory: "5xx",
      });
      throw err;
    }
  };
}
