import { describe, it, expect } from "vitest";
import { TopicSchema, SourceSchema, GraphResponseSchema, DocumentSchema, ConversationMessageSchema } from "./types";

describe("TopicSchema", () => {
  it("parses a valid topic", () => {
    const raw = {
      id: "abc",
      user_id: "user1",
      title: "Test Topic",
      context_summary: null,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    };
    const topic = TopicSchema.parse(raw);
    expect(topic.id).toBe("abc");
    expect(topic.title).toBe("Test Topic");
    expect(topic.context_summary).toBeNull();
  });

  it("rejects missing required fields", () => {
    expect(() => TopicSchema.parse({ id: "abc" })).toThrow();
  });
});

describe("SourceSchema", () => {
  it("parses a valid source", () => {
    const raw = {
      id: "s1",
      topic_id: "t1",
      type: "pdf",
      name: "My Doc",
      blob_url: null,
      extracted_text: "some text",
      created_at: "2026-01-01T00:00:00Z",
    };
    const src = SourceSchema.parse(raw);
    expect(src.type).toBe("pdf");
  });
});

describe("GraphResponseSchema", () => {
  it("parses empty graph", () => {
    const raw = { nodes: [], edges: [] };
    const g = GraphResponseSchema.parse(raw);
    expect(g.nodes).toHaveLength(0);
    expect(g.edges).toHaveLength(0);
  });
});

describe("ConversationMessageSchema", () => {
  it("parses user message", () => {
    const raw = {
      id: "m1",
      topic_id: "t1",
      role: "user",
      content: "Hello",
      created_at: "2026-01-01T00:00:00Z",
    };
    const msg = ConversationMessageSchema.parse(raw);
    expect(msg.role).toBe("user");
  });

  it("rejects invalid role", () => {
    const raw = {
      id: "m1",
      topic_id: "t1",
      role: "system",
      content: "Hello",
      created_at: "2026-01-01T00:00:00Z",
    };
    expect(() => ConversationMessageSchema.parse(raw)).toThrow();
  });
});
