// Chat streaming-send transport for mobile.
//
// On React Native the GLOBAL `fetch` resolves only after the whole body arrives and
// exposes no readable `response.body`, so it cannot stream. `expo/fetch` returns a real
// streaming Response (body is a web ReadableStream) on iOS and Android; the integrator
// wires it as `config.fetchImpl`.
//
// Cancellation is NEVER `for await ... break` — that abandons the reader and leaks the
// socket. The caller aborts an AbortController; the signal flows into handleSSEStream,
// which calls reader.cancel().

import { resolveAuthHeaders } from "./authHeaders";
import type { ClientConfig } from "./config";
import { FetchError } from "./errors";
import { handleSSEStream } from "./stream";
import type { Packet, FileDescriptor, Filters } from "../types";

// Mirrors the backend constant AUTO_PLACE_AFTER_LATEST_MESSAGE (= -1) in models.py.
export const AUTO_PLACE_AFTER_LATEST_MESSAGE = -1;

export type MessageOrigin =
  | "webapp"
  | "chrome_extension"
  | "api"
  | "slackbot"
  | "widget"
  | "discordbot"
  | "unknown"
  | "unset";

export interface LLMOverride {
  model_provider?: string;
  model_version?: string;
  temperature?: number;
}

// TS mirror of the backend `SendMessageRequest` (models.py ~L99). Only `message` is
// required; undefined optionals are omitted from the wire body so the backend applies
// its own defaults (null chat_session_id -> new session; parent_message_id -1 -> auto-place).
export interface SendMessageRequest {
  message: string;

  // -1 -> auto-place after latest (AUTO_PLACE_AFTER_LATEST_MESSAGE);
  // null -> regenerate from root; int -> place after that parent message id.
  parent_message_id?: number | null;
  chat_session_id?: string | null;

  file_descriptors?: FileDescriptor[];

  llm_override?: LLMOverride | null;
  // >1 entry triggers multi-model parallel streaming.
  llm_overrides?: LLMOverride[] | null;

  allowed_tool_ids?: number[] | null;
  forced_tool_id?: number | null;

  internal_search_filters?: Filters | null;

  deep_research?: boolean;
  include_citations?: boolean;

  origin?: MessageOrigin;
  additional_context?: string | null;

  // True (default) -> NDJSON stream; False -> single JSON body. Mobile only streams.
  stream?: boolean;
}

const SEND_MESSAGE_PATH = "/chat/send-chat-message";

async function buildHeaders(config: ClientConfig): Promise<Headers> {
  const headers = await resolveAuthHeaders(config);
  headers.set("Content-Type", "application/json");
  // Backend mislabels the NDJSON stream as text/event-stream; Accept it to match,
  // but it's parsed as NDJSON via handleSSEStream regardless.
  headers.set("Accept", "text/event-stream");
  return headers;
}

// Shared POST for the send path. Throws FetchError (with the parsed body) on a
// non-ok response; success-body handling is left to the caller.
async function postSendMessage(
  req: SendMessageRequest,
  config: ClientConfig,
  stream: boolean,
  signal?: AbortSignal
): Promise<Response> {
  const body = JSON.stringify({ ...req, stream });

  const response = await config.fetchImpl(
    `${config.baseUrl}${SEND_MESSAGE_PATH}`,
    {
      method: "POST",
      headers: await buildHeaders(config),
      body,
      signal,
    }
  );

  if (!response.ok) {
    // Fall back to {} so callers (and the auth handler) can still read `.status`.
    const info = await response.json().catch(() => ({}));
    throw new FetchError(
      `send-message${stream ? "" : " (one-shot)"} failed with status ${response.status}`,
      response.status,
      info
    );
  }

  return response;
}

// Stream a chat message, yielding each decoded NDJSON Packet. Cancel via the
// AbortSignal — do NOT `break` out of the generator. Throws FetchError on non-ok.
export async function* streamChatMessage(
  req: SendMessageRequest,
  config: ClientConfig,
  signal?: AbortSignal
): AsyncGenerator<Packet, void, unknown> {
  const response = await postSendMessage(req, config, true, signal);
  yield* handleSSEStream<Packet>(response, signal);
}
