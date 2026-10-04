// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ConversationMessage, GraphResponse } from "../../lib/types";

const startStream = vi.fn();
const getChatHistory = vi.fn();
const getGraph = vi.fn();

vi.mock("mermaid", () => ({ default: { initialize: vi.fn(), run: vi.fn() } }));
vi.mock("../../hooks/useReadOnly", () => ({ useReadOnly: () => false }));
vi.mock("../../hooks/useSSEStream", () => ({
  useSSEStream: () => ({ isStreaming: false, startStream, stopStream: vi.fn() }),
}));
vi.mock("../../lib/api", () => ({
  addDocumentBlock: vi.fn(),
  getChatHistory: (...args: unknown[]) => getChatHistory(...args),
  getGraph: (...args: unknown[]) => getGraph(...args),
}));

import { ChatTab } from "./ChatTab";

const TOPIC_ID = "topic-1";

const graph = {
  nodes: [{ id: "n1", label: "Theme" }],
  edges: [],
} as unknown as GraphResponse;

const savedExchange = [
  { id: "m1", topic_id: TOPIC_ID, role: "user", content: "starter", created_at: "2026-01-01T00:00:00Z" },
  { id: "m2", topic_id: TOPIC_ID, role: "assistant", content: "themes", created_at: "2026-01-01T00:00:10Z" },
] as ConversationMessage[];

function renderChat(client: QueryClient) {
  return render(
    <QueryClientProvider client={client}>
      <ChatTab topicId={TOPIC_ID} />
    </QueryClientProvider>,
  );
}

describe("ChatTab L0 starter message", () => {
  beforeEach(() => {
    startStream.mockReset();
    getChatHistory.mockReset();
    getGraph.mockReset();
    getGraph.mockResolvedValue(graph);
    Element.prototype.scrollIntoView = vi.fn();
  });

  it("sends the starter once when the server confirms an empty history", async () => {
    getChatHistory.mockResolvedValue([]);
    renderChat(new QueryClient());

    await waitFor(() => expect(startStream).toHaveBeenCalledTimes(1));
    expect(startStream).toHaveBeenCalledWith(`/topics/${TOPIC_ID}/chat`, expect.anything());
  });

  it("does not resend the starter on remount when the cached history is stale", async () => {
    // State left behind when the tab was switched away while the starter was streaming:
    // the cache still says "empty", but the server already saved the exchange.
    const client = new QueryClient();
    client.setQueryData(["chat-history", TOPIC_ID], []);
    client.setQueryData(["graph", TOPIC_ID], graph);
    getChatHistory.mockResolvedValue(savedExchange);

    renderChat(client);

    await waitFor(() =>
      expect(client.getQueryData(["chat-history", TOPIC_ID])).toEqual(savedExchange),
    );
    expect(startStream).not.toHaveBeenCalled();
  });
});
