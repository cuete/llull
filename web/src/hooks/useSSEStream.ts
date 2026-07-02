import { useCallback, useRef, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export interface SSEDoneEvent {
  message_id?: string;
}

export interface SSEStreamOptions {
  onChunk: (chunk: string) => void;
  onDone: (event?: SSEDoneEvent) => void;
  onError: (error: string) => void;
  onTaskCreated?: (taskId: string) => void;
}

export interface SSEStreamState {
  isStreaming: boolean;
  startStream: (path: string, body: Record<string, unknown>) => void;
  stopStream: () => void;
}

/**
 * Custom hook for POST-initiated SSE streams.
 * Posts body as JSON, then reads the response body as a stream of SSE events.
 */
export function useSSEStream(options: SSEStreamOptions): SSEStreamState {
  const [isStreaming, setIsStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const stopStream = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setIsStreaming(false);
  }, []);

  const startStream = useCallback(
    async (path: string, body: Record<string, unknown>) => {
      // Cancel any existing stream
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setIsStreaming(true);

      try {
        const res = await fetch(`${API_BASE}${path}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
          signal: controller.signal,
        });

        if (!res.ok || !res.body) {
          const text = await res.text().catch(() => "Stream failed");
          options.onError(text);
          setIsStreaming(false);
          return;
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        // Track the current SSE event type from `event:` lines
        let currentEventType: string | null = null;

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });

          // Process complete SSE lines
          const lines = buffer.split("\n");
          // Keep incomplete last line in buffer
          buffer = lines.pop() ?? "";

          for (const line of lines) {
            const trimmed = line.trim();

            // Blank line = SSE event boundary; reset event type
            if (!trimmed) {
              currentEventType = null;
              continue;
            }

            if (trimmed.startsWith(":")) continue; // SSE comment

            // Track event type from `event:` field
            if (trimmed.startsWith("event:")) {
              currentEventType = trimmed.slice(6).trim();
              continue;
            }

            if (trimmed.startsWith("data:")) {
              const data = trimmed.slice(5).trim();
              if (data === "[DONE]") {
                options.onDone();
                setIsStreaming(false);
                return;
              }
              try {
                const parsed = JSON.parse(data) as Record<string, unknown>;

                // Handle backend-style SSE: event type in `event:` field, payload in `data:`
                if (currentEventType === "token") {
                  // Backend emits: event: token / data: {"text": "..."}
                  const text = parsed["text"];
                  if (typeof text === "string") {
                    options.onChunk(text);
                  }
                  continue;
                }
                if (currentEventType === "done") {
                  options.onDone(parsed as SSEDoneEvent);
                  setIsStreaming(false);
                  return;
                }
                if (currentEventType === "error") {
                  options.onError(
                    typeof parsed["message"] === "string" ? parsed["message"] : "Stream error",
                  );
                  setIsStreaming(false);
                  return;
                }

                // Fallback: legacy format using `type` field in data payload
                const type = parsed["type"] as string | undefined;
                if (type === "chunk" && typeof parsed["content"] === "string") {
                  options.onChunk(parsed["content"]);
                } else if (type === "done") {
                  options.onDone();
                  setIsStreaming(false);
                  return;
                } else if (type === "error") {
                  options.onError(
                    typeof parsed["error"] === "string" ? parsed["error"] : "Stream error",
                  );
                  setIsStreaming(false);
                  return;
                } else if (type === "task_created" && typeof parsed["task_id"] === "string") {
                  options.onTaskCreated?.(parsed["task_id"]);
                } else if (!currentEventType) {
                  // Plain text chunk fallback (no event type, no known type field)
                  options.onChunk(data);
                }
              } catch {
                // Not JSON — treat as raw text
                if (data && data !== "[DONE]") {
                  options.onChunk(data);
                }
              }
            }
          }
        }

        options.onDone();
      } catch (error) {
        if (error instanceof Error && error.name === "AbortError") {
          // User stopped — not an error
          return;
        }
        options.onError(error instanceof Error ? error.message : "Unknown error");
      } finally {
        setIsStreaming(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  return { isStreaming, startStream, stopStream };
}
