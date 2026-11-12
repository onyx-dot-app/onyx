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
  /** Adds an internal search step between the image step and the answer. */
  searchAfterImage?: boolean;
}

interface MockPlacement {
  turn_index: number;
  tab_index: number;
  sub_turn_index?: number;
}

function imageGenerationPackets(
  placement: MockPlacement,
  fileId: string,
  revisedPrompt: string
): Record<string, unknown>[] {
  return [
    { placement, obj: { type: "image_generation_start" } },
    {
      placement,
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
    { placement, obj: { type: "section_end" } },
  ];
}

function answerPackets(
  turnIndex: number,
  agentMessageId: number,
  message: string,
  fileId: string
): Record<string, unknown>[] {
  const placement = { turn_index: turnIndex, tab_index: 0 };
  return [
    {
      placement,
      obj: {
        type: "message_start",
        id: `mock-${agentMessageId}`,
        content: message,
        final_documents: null,
      },
    },
    { placement, obj: { type: "stop", stop_reason: "finished" } },
    {
      message_id: agentMessageId,
      citations: {},
      files: [{ id: fileId, type: "image" }],
    },
  ];
}

export function buildMockImageGenStream({
  fileId,
  revisedPrompt,
  message,
  searchAfterImage = false,
}: ImageGenStreamOptions): string {
  const { userMessageId, agentMessageId } = nextMessageIds();
  const search = { turn_index: 1, tab_index: 0 };

  const packets = [
    {
      user_message_id: userMessageId,
      reserved_assistant_message_id: agentMessageId,
    },
    ...imageGenerationPackets(
      { turn_index: 0, tab_index: 0 },
      fileId,
      revisedPrompt
    ),
    ...(searchAfterImage
      ? [
          { placement: search, obj: { type: "search_tool_start" } },
          {
            placement: search,
            obj: { type: "search_tool_queries_delta", queries: ["onyx"] },
          },
          { placement: search, obj: { type: "section_end" } },
        ]
      : []),
    ...answerPackets(searchAfterImage ? 2 : 1, agentMessageId, message, fileId),
  ];

  return serializePackets(packets);
}

export interface CodeModeCellStreamOptions {
  code: string;
  /** The custom tool the program calls; the call outlives the first observation. */
  toolName: string;
  toolOutput: string;
  message: string;
  /**
   * "wait": a wait_code call reports the call's end and the program's end.
   * "response_end": the answer arrives while the cell runs, and the closing
   * record reports the rest.
   */
  end: "wait" | "response_end";
}

/** A code mode cell that yields during a tool call, then completes or stops
 * with the response. */
export function buildMockCodeModeCellStream({
  code,
  toolName,
  toolOutput,
  message,
  end,
}: CodeModeCellStreamOptions): string {
  const { userMessageId, agentMessageId } = nextMessageIds();
  const cell = { turn_index: 0, tab_index: 0 };
  const wait = { turn_index: 1, tab_index: 0 };
  const waits = end === "wait";
  const answer = { turn_index: waits ? 2 : 1, tab_index: 0 };
  const callStart = (at: typeof cell) => ({
    placement: { ...at, sub_turn_index: 0 },
    obj: {
      type: "custom_tool_start",
      tool_name: toolName,
      display_name: toolName,
    },
  });
  const callEnd = (at: typeof cell) => [
    {
      placement: { ...at, sub_turn_index: 0 },
      obj: {
        type: "custom_tool_delta",
        tool_name: toolName,
        display_name: toolName,
        response_type: "text",
        data: toolOutput,
      },
    },
    { placement: { ...at, sub_turn_index: 0 }, obj: { type: "section_end" } },
  ];

  const yielded = [
    {
      placement: cell,
      obj: {
        type: "tool_call_argument_delta",
        tool_type: "execute_code",
        tool_id: "call-code",
        argument_deltas: { code },
      },
    },
    {
      placement: cell,
      obj: { type: "code_mode_start", code, cell_id: null, observation: 0 },
    },
    callStart(cell),
    {
      placement: cell,
      obj: {
        type: "code_mode_delta",
        stdout: "program output\n",
        status: "running",
        duration_seconds: 30,
        tool_call_count: 1,
        cell_id: 1,
        observation: 0,
      },
    },
    { placement: cell, obj: { type: "section_end" } },
  ];
  const waited = [
    {
      placement: wait,
      obj: { type: "code_mode_start", code: "", cell_id: 1, observation: 1 },
    },
    callStart(wait),
    ...callEnd(wait),
    {
      placement: wait,
      obj: {
        type: "code_mode_delta",
        stdout: "",
        result: "done",
        status: "completed",
        duration_seconds: 41,
        tool_call_count: 1,
        cell_id: 1,
        observation: 1,
      },
    },
    { placement: wait, obj: { type: "section_end" } },
  ];
  // The closing record: the calls that ended after the observation, then the
  // final status.
  const closing = [
    ...callEnd(cell),
    {
      placement: cell,
      obj: {
        type: "code_mode_delta",
        stdout: "",
        status: "terminated",
        tool_call_count: 1,
        response_ended: true,
      },
    },
  ];

  const packets = [
    {
      user_message_id: userMessageId,
      reserved_assistant_message_id: agentMessageId,
    },
    ...yielded,
    ...(waits ? waited : []),
    {
      placement: answer,
      obj: {
        type: "message_start",
        id: `mock-${agentMessageId}`,
        content: message,
        final_documents: null,
      },
    },
    // The closing record of a running cell follows the answer, live and on
    // reload.
    ...(waits ? [] : closing),
    { placement: answer, obj: { type: "stop", stop_reason: "finished" } },
    { message_id: agentMessageId, citations: {}, files: [] },
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
