/** Build typed NDJSON streams for chat browser tests. */
import type { Page } from "@playwright/test";
import type {
  ChatItem,
  Packet,
  PacketIdentity,
} from "@/app/app/services/streamingModels";
import { StopReason } from "@/app/app/services/streamingModels";
import type { OnyxDocument } from "@/lib/search/interfaces";

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

function itemPacket(
  responseId: number,
  messageId: string,
  item: ChatItem
): Packet {
  const identity: PacketIdentity = {
    response_id: responseId,
    run_id: `run-${responseId}`,
    message_id: messageId,
    part_id: item.kind,
  };
  if (item.kind === "tool") identity.tool_call_id = `call-${messageId}`;
  return {
    identity,
    obj: { type: "item_update", item },
  };
}

function answerPacket(
  responseId: number,
  text: string,
  documents: OnyxDocument[] = [],
  citations: Record<number, string> = {}
): Packet {
  return itemPacket(responseId, `answer-${responseId}`, {
    kind: "text",
    text,
    purpose: "answer",
    status: "complete",
    documents,
    citations: Object.entries(citations).map(([number, document_id]) => ({
      citation_number: Number(number),
      document_id,
    })),
  });
}

function serializeStream(
  userMessageId: number,
  agentMessageId: number,
  packets: Packet[],
  citations: Record<number, string> = {},
  files: { id: string; type: string }[] = []
): string {
  const stop: Packet = {
    obj: { type: "stop", stop_reason: StopReason.FINISHED },
  };
  return (
    [
      {
        user_message_id: userMessageId,
        reserved_assistant_message_id: agentMessageId,
      },
      ...packets,
      stop,
      { message_id: agentMessageId, citations, files },
    ]
      .map((packet) => JSON.stringify(packet))
      .join("\n") + "\n"
  );
}

export function buildMockStream(content: string): string {
  const { userMessageId, agentMessageId } = nextMessageIds();
  return serializeStream(userMessageId, agentMessageId, [
    answerPacket(agentMessageId, content),
  ]);
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
  return serializeStream(
    userMessageId,
    agentMessageId,
    [
      itemPacket(agentMessageId, `image-${agentMessageId}`, {
        kind: "tool",
        name: "generate_image",
        arguments: {},
        status: "complete",
        output: "",
        metadata: {
          type: "image_generation_result",
          generated_images: [
            {
              file_id: fileId,
              url: `/api/chat/file/${fileId}`,
              revised_prompt: revisedPrompt,
              shape: "square",
            },
          ],
        },
      }),
      answerPacket(agentMessageId, message),
    ],
    {},
    [{ id: fileId, type: "image" }]
  );
}

export type MockDocument = Pick<
  OnyxDocument,
  | "document_id"
  | "semantic_identifier"
  | "link"
  | "source_type"
  | "blurb"
  | "is_internet"
>;

export interface SearchMockOptions {
  content: string;
  queries: string[];
  documents: MockDocument[];
  citations: Record<number, string>;
  isInternetSearch?: boolean;
}

export function buildMockSearchStream(options: SearchMockOptions): string {
  const { userMessageId, agentMessageId } = nextMessageIds();
  const documents: OnyxDocument[] = options.documents.map((doc) => ({
    ...doc,
    boost: 0,
    hidden: false,
    score: 0.95,
    chunk_ind: 0,
    match_highlights: [],
    metadata: {},
    updated_at: null,
  }));
  return serializeStream(
    userMessageId,
    agentMessageId,
    [
      itemPacket(agentMessageId, `search-${agentMessageId}`, {
        kind: "tool",
        name: options.isInternetSearch ? "web_search" : "internal_search",
        arguments: { queries: options.queries },
        status: "complete",
        output: "",
        metadata: {
          type: "search_result",
          queries: options.queries,
          sources: [],
          time_filter_start: null,
          time_filter_end: null,
          search_docs: documents,
          displayed_docs: null,
          citation_mapping: options.citations,
        },
      }),
      answerPacket(
        agentMessageId,
        options.content,
        documents,
        options.citations
      ),
    ],
    options.citations
  );
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
