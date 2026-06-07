import { z } from "zod";

// ─── Topic ───────────────────────────────────────────────────────────────────

export const TopicSchema = z.object({
  id: z.string(),
  user_id: z.string(),
  title: z.string(),
  context_summary: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});

export type Topic = z.infer<typeof TopicSchema>;

export const TopicListSchema = z.array(TopicSchema);

// ─── Source ──────────────────────────────────────────────────────────────────

export const FactCheckClaimSchema = z.object({
  claim: z.string(),
  verdict: z.enum(["verified", "contradicted", "unverified"]),
  evidence: z.string(),
  source_url: z.string(),
});

export type FactCheckClaim = z.infer<typeof FactCheckClaimSchema>;

export const FactCheckResponseSchema = z.object({
  claims: z.array(FactCheckClaimSchema),
  fact_check_score: z.number(),
  quality_score_updated: z.number().nullable(),
});

export type FactCheckResponse = z.infer<typeof FactCheckResponseSchema>;

export const SourceSchema = z.object({
  id: z.string(),
  topic_id: z.string(),
  type: z.string(),
  name: z.string(),
  blob_url: z.string().nullable(),
  source_url: z.string().nullable().optional(),
  extracted_text: z.string(),
  created_at: z.string(),
  // Quality ratings
  ai_suspicion: z.number().nullable().optional(),
  ai_suspicion_reason: z.string().nullable().optional(),
  quality_score: z.number().nullable().optional(),
  quality_reason: z.string().nullable().optional(),
  fact_check_result: z.string().nullable().optional(),
  fact_check_score: z.number().nullable().optional(),
});

export type Source = z.infer<typeof SourceSchema>;

export const SourceListSchema = z.array(SourceSchema);

// ─── Graph ───────────────────────────────────────────────────────────────────

export const NodeSchema = z.object({
  id: z.string(),
  topic_id: z.string(),
  source_id: z.string(),
  label: z.string(),
  description: z.string(),
  status: z.enum(["unexplored", "zoomed"]),
  created_at: z.string(),
});

export type GraphNode = z.infer<typeof NodeSchema>;

export const EdgeSchema = z.object({
  id: z.string(),
  from_node_id: z.string(),
  to_node_id: z.string(),
  type: z.enum(["relational", "hierarchical", "causal"]),
  weight: z.number(),
  confidence: z.number(),
  created_at: z.string(),
});

export type GraphEdge = z.infer<typeof EdgeSchema>;

export const GraphResponseSchema = z.object({
  nodes: z.array(NodeSchema),
  edges: z.array(EdgeSchema),
});

export type GraphResponse = z.infer<typeof GraphResponseSchema>;

// ─── Document ────────────────────────────────────────────────────────────────

export const DocumentBlockSchema = z.object({
  id: z.string(),
  document_id: z.string(),
  source_id: z.string().nullable(),
  content_md: z.string(),
  order: z.number(),
});

export type DocumentBlock = z.infer<typeof DocumentBlockSchema>;

export const DocumentSchema = z.object({
  id: z.string(),
  topic_id: z.string(),
  route_summary: z.string().nullable(),
  updated_at: z.string(),
  blocks: z.array(DocumentBlockSchema),
});

export type Document = z.infer<typeof DocumentSchema>;

// ─── Conversation ─────────────────────────────────────────────────────────────

export const ConversationMessageSchema = z.object({
  id: z.string(),
  topic_id: z.string(),
  role: z.enum(["user", "assistant"]),
  content: z.string(),
  created_at: z.string(),
});

export type ConversationMessage = z.infer<typeof ConversationMessageSchema>;

export const ConversationListSchema = z.array(ConversationMessageSchema);

// ─── Task ────────────────────────────────────────────────────────────────────

export const TaskSchema = z.object({
  id: z.string(),
  user_id: z.string(),
  topic_id: z.string().nullable(),
  type: z.enum(["source_ingest", "analyze_l0", "zoom", "export"]),
  status: z.enum(["pending", "running", "done", "failed"]),
  progress: z.number(),
  result: z.unknown().nullable(),
  error: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});

export type Task = z.infer<typeof TaskSchema>;

// ─── SSE ─────────────────────────────────────────────────────────────────────

export interface SSEChunk {
  type: "chunk" | "done" | "error" | "task_created";
  content?: string;
  task_id?: string;
  error?: string;
}

// ─── Settings ────────────────────────────────────────────────────────────────

export interface LLMSettings {
  provider: "openai" | "anthropic" | "ollama";
  model: string;
  apiKey: string;
  ollamaBaseUrl: string;
}

export const DEFAULT_LLM_SETTINGS: LLMSettings = {
  provider: "anthropic",
  model: "claude-sonnet-4-5",
  apiKey: "",
  ollamaBaseUrl: "http://localhost:11434",
};
