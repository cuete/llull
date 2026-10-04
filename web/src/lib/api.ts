import { z } from "zod";
import {
  ConversationListSchema,
  DocumentSchema,
  FactCheckResponseSchema,
  GraphResponseSchema,
  HealthSchema,
  SourceListSchema,
  SourceSchema,
  TaskSchema,
  TopicListSchema,
  TopicSchema,
  type ConversationMessage,
  type Document,
  type FactCheckResponse,
  type GraphResponse,
  type Health,
  type Source,
  type Task,
  type Topic,
} from "./types";
import { getIdToken } from "./msal";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Authorization header for the signed-in Microsoft account, if any. Empty when auth isn't configured. */
async function authHeaders(): Promise<Record<string, string>> {
  const token = await getIdToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function apiFetch<T>(
  path: string,
  schema: z.ZodType<T>,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(await authHeaders()), ...init?.headers },
    ...init,
  });

  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new ApiError(res.status, text);
  }

  const json: unknown = await res.json();
  return schema.parse(json);
}

// ─── Health ──────────────────────────────────────────────────────────────────

export async function getHealth(): Promise<Health> {
  return apiFetch("/health", HealthSchema);
}

// ─── Topics ──────────────────────────────────────────────────────────────────

export async function listTopics(): Promise<Topic[]> {
  return apiFetch("/topics", TopicListSchema);
}

export async function getTopic(id: string): Promise<Topic> {
  return apiFetch(`/topics/${id}`, TopicSchema);
}

export async function createTopic(title: string): Promise<Topic> {
  return apiFetch("/topics", TopicSchema, {
    method: "POST",
    body: JSON.stringify({ title }),
  });
}

export async function deleteTopic(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/topics/${id}`, { method: "DELETE", headers: await authHeaders() });
  if (!res.ok) throw new ApiError(res.status, `Delete topic failed: ${res.status}`);
}

export async function patchTopic(id: string, data: { title?: string; context_summary?: string }): Promise<Topic> {
  return apiFetch(`/topics/${id}`, TopicSchema, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

// ─── Sources ─────────────────────────────────────────────────────────────────

export async function listSources(topicId: string): Promise<Source[]> {
  return apiFetch(`/topics/${topicId}/sources`, SourceListSchema);
}

export async function deleteSource(topicId: string, sourceId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/topics/${topicId}/sources/${sourceId}`, {
    method: "DELETE",
    headers: await authHeaders(),
  });
  if (!res.ok) throw new ApiError(res.status, `Delete source failed: ${res.status}`);
}

export async function addSourceUrl(topicId: string, name: string, url: string): Promise<{ task_id: string }> {
  const form = new FormData();
  form.append("source_type", "url");
  form.append("name", name);
  form.append("content", url);
  const res = await fetch(`${API_BASE}/topics/${topicId}/sources`, { method: "POST", body: form, headers: await authHeaders() });
  if (!res.ok) throw new ApiError(res.status, `Add source failed: ${res.status}`);
  return res.json() as Promise<{ task_id: string }>;
}

export async function addSourceText(topicId: string, name: string, text: string): Promise<{ task_id: string }> {
  const form = new FormData();
  form.append("source_type", "text");
  form.append("name", name);
  form.append("content", text);
  const res = await fetch(`${API_BASE}/topics/${topicId}/sources`, { method: "POST", body: form, headers: await authHeaders() });
  if (!res.ok) throw new ApiError(res.status, `Add source failed: ${res.status}`);
  return res.json() as Promise<{ task_id: string }>;
}

export async function addSourceFile(topicId: string, file: File): Promise<{ task_id: string }> {
  const form = new FormData();
  form.append("source_type", "file");
  form.append("name", file.name);
  form.append("file", file);
  const res = await fetch(`${API_BASE}/topics/${topicId}/sources`, { method: "POST", body: form, headers: await authHeaders() });
  if (!res.ok) throw new ApiError(res.status, `Add source failed: ${res.status}`);
  return res.json() as Promise<{ task_id: string }>;
}

export async function patchSource(topicId: string, sourceId: string, name: string): Promise<Source> {
  return apiFetch(`/topics/${topicId}/sources/${sourceId}`, SourceSchema, {
    method: "PATCH",
    body: JSON.stringify({ name }),
  });
}

export async function factCheckSource(
  topicId: string,
  sourceId: string,
): Promise<FactCheckResponse> {
  return apiFetch(
    `/topics/${topicId}/sources/${sourceId}/fact-check`,
    FactCheckResponseSchema,
    { method: "POST" },
  );
}

// ─── Graph ───────────────────────────────────────────────────────────────────

export async function getGraph(topicId: string): Promise<GraphResponse> {
  return apiFetch(`/topics/${topicId}/graph`, GraphResponseSchema);
}

// ─── Document ────────────────────────────────────────────────────────────────

export async function getDocument(topicId: string): Promise<Document> {
  return apiFetch(`/topics/${topicId}/document`, DocumentSchema);
}

export async function patchDocumentBlock(
  topicId: string,
  blockId: string,
  content_md: string,
): Promise<void> {
  const res = await fetch(`${API_BASE}/topics/${topicId}/document/blocks/${blockId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify({ content_md }),
  });
  if (!res.ok) throw new ApiError(res.status, `Patch block failed: ${res.status}`);
}

export async function addDocumentBlock(
  topicId: string,
  content_md: string,
  source = "chat",
): Promise<void> {
  const res = await fetch(`${API_BASE}/topics/${topicId}/document/blocks`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify({ content_md, source }),
  });
  if (!res.ok) throw new ApiError(res.status, `Add block failed: ${res.status}`);
}

// ─── Conversation ─────────────────────────────────────────────────────────────

export async function getChatHistory(topicId: string): Promise<ConversationMessage[]> {
  return apiFetch(`/topics/${topicId}/chat`, ConversationListSchema);
}

// ─── Task ────────────────────────────────────────────────────────────────────

export async function getTask(taskId: string): Promise<Task> {
  return apiFetch(`/tasks/${taskId}`, TaskSchema);
}

// ─── Analysis ────────────────────────────────────────────────────────────────

export type AnalysisSSEEvent =
  | { type: "progress"; data: { step: string; pct: number } }
  | { type: "nodes_updated"; data: { new_nodes: unknown[]; new_edges: unknown[] } }
  | { type: "document_updated"; data: { blocks: number } }
  | {
      type: "done";
      data: {
        source_id: string;
        nodes: number;
        edges: number;
        /** True when the map was built from a sample of the text, not all of it */
        sampled?: boolean;
        read_tokens?: number;
        content_tokens?: number;
      };
    }
  | { type: "error"; data: { code: string; message: string } };

/**
 * Stream analysis SSE events from POST /topics/{topicId}/analyze.
 * Calls onEvent for each parsed SSE event; resolves when the stream ends.
 */
export async function analyzeTopicStream(
  topicId: string,
  onEvent: (event: AnalysisSSEEvent) => void,
  force = false,
): Promise<void> {
  const res = await fetch(`${API_BASE}/topics/${topicId}/analyze${force ? "?force=true" : ""}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
  });

  if (!res.ok || !res.body) {
    const text = await res.text().catch(() => res.statusText);
    throw new ApiError(res.status, text);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  let currentEventType: string | null = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });

    const lines = buf.split("\n");
    // Keep the last potentially-incomplete line in the buffer
    buf = lines.pop() ?? "";

    for (const line of lines) {
      if (line.startsWith("event:")) {
        currentEventType = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        const dataStr = line.slice(5).trim();
        if (currentEventType) {
          try {
            const data: unknown = JSON.parse(dataStr);
            onEvent({ type: currentEventType, data } as AnalysisSSEEvent);
          } catch {
            // Ignore malformed JSON lines
          }
        }
        currentEventType = null;
      } else if (line === "") {
        currentEventType = null;
      }
    }
  }
}

// ─── Zoom ────────────────────────────────────────────────────────────────────

export type ZoomSSEEvent =
  | { type: "progress"; data: { step: string } }
  | {
      type: "done";
      data: { sub_nodes: number; new_links?: number; revised_links?: number; fully_read?: boolean };
    }
  | { type: "error"; data: { code: string; message: string } };

/**
 * Stream zoom SSE events from POST /topics/{topicId}/zoom/{nodeId}.
 * Calls onEvent for each parsed SSE event; resolves when stream ends.
 */
export async function zoomNodeStream(
  topicId: string,
  nodeId: string,
  onEvent: (event: ZoomSSEEvent) => void,
): Promise<void> {
  const res = await fetch(`${API_BASE}/topics/${topicId}/zoom/${nodeId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify({}),
  });

  if (!res.ok || !res.body) {
    const text = await res.text().catch(() => res.statusText);
    throw new ApiError(res.status, text);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  let currentEventType: string | null = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });

    const lines = buf.split("\n");
    buf = lines.pop() ?? "";

    for (const line of lines) {
      if (line.startsWith("event:")) {
        currentEventType = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        const dataStr = line.slice(5).trim();
        if (currentEventType) {
          try {
            const data: unknown = JSON.parse(dataStr);
            onEvent({ type: currentEventType, data } as ZoomSSEEvent);
            if (currentEventType === "done" || currentEventType === "error") {
              return;
            }
          } catch {
            // Ignore malformed JSON
          }
        }
        currentEventType = null;
      } else if (line === "") {
        currentEventType = null;
      }
    }
  }
}

// ─── SSE helpers ─────────────────────────────────────────────────────────────

export function buildChatSSEUrl(topicId: string): string {
  return `${API_BASE}/topics/${topicId}/chat`;
}

export function buildAnalyzeSSEUrl(topicId: string): string {
  return `${API_BASE}/topics/${topicId}/analyze`;
}

export function buildTaskStreamUrl(taskId: string): string {
  return `${API_BASE}/tasks/${taskId}/stream`;
}

export { ApiError };
