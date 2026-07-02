const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);
const DEMO_MESSAGE = "Demo mode: this instance is read-only. Modifications are disabled.";

export const DEMO_MODE = import.meta.env.VITE_DEMO_MODE === "true";

let initialized = false;

/**
 * Wraps window.fetch to short-circuit any non-GET request to the API with a
 * synthetic 403, when demo mode is enabled. Mirrors the backend's own
 * DEMO_MODE middleware (service/app/main.py) so blocked calls never leave
 * the browser. Call once at app startup (main.tsx), before initApiFetchLogger
 * so blocked requests still show up in the Logs drawer.
 */
export function initDemoModeGuard(): void {
  if (initialized || !DEMO_MODE) return;
  initialized = true;

  const originalFetch = window.fetch.bind(window);

  window.fetch = async (
    input: RequestInfo | URL,
    init?: RequestInit,
  ): Promise<Response> => {
    const method = (
      init?.method ?? (input instanceof Request ? input.method : "GET")
    ).toUpperCase();
    const url = typeof input === "string"
      ? input
      : input instanceof URL
        ? input.toString()
        : input.url;

    if (url.startsWith(API_BASE) && !SAFE_METHODS.has(method)) {
      return new Response(JSON.stringify({ detail: DEMO_MESSAGE }), {
        status: 403,
        statusText: "Forbidden",
        headers: { "Content-Type": "application/json" },
      });
    }

    return originalFetch(input, init);
  };
}
