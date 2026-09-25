/**
 * Shared helpers for mocking the chat streaming endpoint in Playwright specs.
 *
 * The helpers fall into two layers:
 *   1. `buildMock*Stream` — construct NDJSON response bodies matching the
 *      shape produced by `/api/chat/send-chat-message`.
 *   2. `mockChatEndpoint` / `mockChatEndpointSequence` — register
 *      `page.route` handlers that fulfill the endpoint with a provided body.
 *
 * Specs that share a module instance (same worker process) share the
 * `turnCounter` used to generate unique message IDs. Call
 * `resetTurnCounter()` in `beforeEach` so IDs start fresh per test.
 */

import type { Page } from "@playwright/test";

let turnCounter = 0;

export function resetTurnCounter(): void {
  turnCounter = 0;
}

function nextMessageIds(): { userMessageId: number; agentMessageId: number } {
  turnCounter += 1;
  return {
    userMessageId: turnCounter * 100 + 1,
    agentMessageId: turnCounter * 100 + 2,
  };
}

function serializePackets(packets: unknown[]): string {
  return `${packets.map((p) => JSON.stringify(p)).join("\n")}\n`;
}

export function buildMockStream(content: string): string {
  const { userMessageId, agentMessageId } = nextMessageIds();

  const packets = [
    {
      user_message_id: userMessageId,
      reserved_assistant_message_id: agentMessageId,
    },
    {
      placement: { turn_index: 0, tab_index: 0 },
      obj: {
        type: "message_start",
        id: `mock-${agentMessageId}`,
        content,
        final_documents: null,
      },
    },
    {
      placement: { turn_index: 0, tab_index: 0 },
      obj: { type: "stop", stop_reason: "finished" },
    },
    {
      message_id: agentMessageId,
      citations: {},
      files: [],
    },
  ];

  return serializePackets(packets);
}

export interface ImageGenStreamOptions {
  fileId: string;
  revisedPrompt: string;
  message: string;
}

export function buildMockImageGenStream({
  fileId,
  revisedPrompt,
  message,
}: ImageGenStreamOptions): string {
  const { userMessageId, agentMessageId } = nextMessageIds();

  const packets = [
    {
      user_message_id: userMessageId,
      reserved_assistant_message_id: agentMessageId,
    },
    {
      placement: { turn_index: 0, tab_index: 0 },
      obj: { type: "image_generation_start" },
    },
    {
      placement: { turn_index: 0, tab_index: 0 },
      obj: {
        type: "image_generation_final",
        images: [
          {
            file_id: fileId,
            url: `/api/chat/file/${fileId}`,
            revised_prompt: revisedPrompt,
            shape: "square",
          },
        ],
      },
    },
    {
      placement: { turn_index: 0, tab_index: 0 },
      obj: { type: "section_end" },
    },
    {
      placement: { turn_index: 1, tab_index: 0 },
      obj: {
        type: "message_start",
        id: `mock-${agentMessageId}`,
        content: message,
        final_documents: null,
      },
    },
    {
      placement: { turn_index: 1, tab_index: 0 },
      obj: { type: "stop", stop_reason: "finished" },
    },
    {
      message_id: agentMessageId,
      citations: {},
      files: [{ id: fileId, type: "image" }],
    },
  ];

  return serializePackets(packets);
}

export interface MockDocument {
  document_id: string;
  semantic_identifier: string;
  link: string;
  source_type: string;
  blurb: string;
  is_internet: boolean;
}

export interface SearchMockOptions {
  content: string;
  queries: string[];
  documents: MockDocument[];
  /** Maps citation number -> document_id */
  citations: Record<number, string>;
  isInternetSearch?: boolean;
}

export function buildMockSearchStream(options: SearchMockOptions): string {
  const { userMessageId, agentMessageId } = nextMessageIds();

  const fullDocs = options.documents.map((doc) => ({
    ...doc,
    boost: 0,
    hidden: false,
    score: 0.95,
    chunk_ind: 0,
    match_highlights: [],
    metadata: {},
    updated_at: null,
  }));

  // Turn 0: search tool
  // Turn 1: answer + citations
  const packets: Record<string, unknown>[] = [
    {
      user_message_id: userMessageId,
      reserved_assistant_message_id: agentMessageId,
    },
    {
      placement: { turn_index: 0, tab_index: 0 },
      obj: {
        type: "search_tool_start",
        ...(options.isInternetSearch !== undefined && {
          is_internet_search: options.isInternetSearch,
        }),
      },
    },
    {
      placement: { turn_index: 0, tab_index: 0 },
      obj: { type: "search_tool_queries_delta", queries: options.queries },
    },
    {
      placement: { turn_index: 0, tab_index: 0 },
      obj: { type: "search_tool_documents_delta", documents: fullDocs },
    },
    {
      placement: { turn_index: 0, tab_index: 0 },
      obj: { type: "section_end" },
    },
    {
      placement: { turn_index: 1, tab_index: 0 },
      obj: {
        type: "message_start",
        id: `mock-${agentMessageId}`,
        content: options.content,
        final_documents: fullDocs,
      },
    },
    ...Object.entries(options.citations).map(([num, docId]) => ({
      placement: { turn_index: 1, tab_index: 0 },
      obj: {
        type: "citation_info",
        citation_number: Number(num),
        document_id: docId,
      },
    })),
    {
      placement: { turn_index: 1, tab_index: 0 },
      obj: { type: "stop", stop_reason: "finished" },
    },
    {
      message_id: agentMessageId,
      citations: options.citations,
      files: [],
    },
  ];

  return serializePackets(packets);
}

/**
 * Registers a route that fulfills every call to the chat streaming endpoint
 * with the provided pre-built NDJSON body.
 */
export async function mockChatEndpoint(
  page: Page,
  body: string
): Promise<void> {
  await page.route("**/api/chat/send-chat-message", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "text/plain",
      body,
    });
  });
}

/**
 * Registers a route that returns a different `buildMockStream(content)` body
 * for each successive call. Calls beyond the list length reuse the last entry.
 */
export async function mockChatEndpointSequence(
  page: Page,
  contents: string[]
): Promise<void> {
  let callIndex = 0;
  await page.route("**/api/chat/send-chat-message", async (route) => {
    const content =
      contents[Math.min(callIndex, contents.length - 1)] ??
      contents[contents.length - 1]!;
    callIndex += 1;
    await route.fulfill({
      status: 200,
      contentType: "text/plain",
      body: buildMockStream(content),
    });
  });
}
