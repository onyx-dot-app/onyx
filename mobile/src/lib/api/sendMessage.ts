// sendMessage.ts — the chat STREAMING SEND transport for mobile.
//
// streamChatMessage is the one network call that has to actually *stream*. On React Native the
// GLOBAL `fetch` resolves its Response only after the whole body arrives and exposes
// no readable `response.body` — so it cannot stream. `expo/fetch` returns a real
// streaming Response whose `body` is a web ReadableStream on both iOS and Android.
// The integrator wires `config.fetchImpl = expoFetch` (see integration notes); this
// module stays transport-neutral and just consumes `config.fetchImpl`.
//
// The body wire-format mirrors the backend `SendMessageRequest` pydantic model
// (backend/onyx/server/query_and_chat/models.py, ~line 99). The response is NDJSON
// (newline-delimited JSON) mislabeled `text/event-stream` — we read it with the
// shared `handleSSEStream` reader (getReader + TextDecoder + line buffering). NEVER
// swap that for an SSE/EventSource client: it would silently drop every packet.
//
// Cancellation is NEVER `for await ... break` — that abandons the reader and leaks the
// socket. The caller aborts an `AbortController`; the signal flows into `handleSSEStream`,
// which calls `reader.cancel()`. See 07-networking-streaming-auth.md.

import { resolveAuthHeaders } from "./authHeaders";
import type { ClientConfig } from "./config";
import { FetchError } from "./errors";
import { handleSSEStream } from "./stream";
import type { Packet, FileDescriptor, Filters } from "../types";

// Auto-place after the latest message in the chain. Mirrors the backend constant
// AUTO_PLACE_AFTER_LATEST_MESSAGE (= -1) in models.py.
export const AUTO_PLACE_AFTER_LATEST_MESSAGE = -1;

/** Telemetry origin tag forwarded to the backend (MessageOrigin enum). */
export type MessageOrigin =
  | "webapp"
  | "chrome_extension"
  | "api"
  | "slackbot"
  | "widget"
  | "discordbot"
  | "unknown"
  | "unset";

/** Per-request LLM override (subset of the backend LLMOverride model). */
export interface LLMOverride {
  model_provider?: string;
  model_version?: string;
  temperature?: number;
}

/**
 * TS mirror of the backend `SendMessageRequest` (models.py ~L99).
 *
 * Only `message` is required. `chat_session_id` / `parent_message_id` default per
 * the backend: a null `chat_session_id` (with no `chat_session_info`) makes the
 * backend create a fresh session; `parent_message_id = -1` auto-places the new turn
 * after the latest message in the chain. Optional fields are omitted from the wire
 * body when undefined so the backend applies its own defaults.
 */
export interface SendMessageRequest {
  message: string;

  // Placement in the conversation tree:
  //   -1   -> auto-place after latest message in chain (AUTO_PLACE_AFTER_LATEST_MESSAGE)
  //   null -> regeneration from root
  //   int  -> place after that specific parent message id
  parent_message_id?: number | null;
  chat_session_id?: string | null;

  file_descriptors?: FileDescriptor[];

  llm_override?: LLMOverride | null;
  // Multi-model parallel generation (>1 entry triggers multi-model streaming).
  llm_overrides?: LLMOverride[] | null;

  allowed_tool_ids?: number[] | null;
  forced_tool_id?: number | null;

  /** Internal search filters (enabled source_type[], document sets, time). */
  internal_search_filters?: Filters | null;

  deep_research?: boolean;
  include_citations?: boolean;

  origin?: MessageOrigin;
  additional_context?: string | null;

  // When True (default) the backend returns an NDJSON stream; when False it returns
  // a single JSON body. Mobile only ever streams (see streamChatMessage).
  stream?: boolean;
}

// Root-relative path (no `/api` — that's the web-only Next.js proxy prefix). The
// mobile client talks to the backend directly, like the other query/mutation paths.
const SEND_MESSAGE_PATH = "/chat/send-chat-message";

async function buildHeaders(config: ClientConfig): Promise<Headers> {
  // Merge any auth headers (mobile: a bearer PAT) the platform supplies.
  const headers = await resolveAuthHeaders(config);
  headers.set("Content-Type", "application/json");
  // The backend mislabels the NDJSON stream as text/event-stream; we Accept it to
  // match, but parse it as NDJSON via handleSSEStream regardless.
  headers.set("Accept", "text/event-stream");
  return headers;
}

/**
 * Shared POST for the send path: builds the wire body (`{ ...req, stream }`),
 * issues the POST via the platform fetch with the merged auth headers, and throws
 * `FetchError` on a non-ok response (with the parsed body). The success-body handling
 * (NDJSON stream) is left to the caller.
 *
 * @throws FetchError on a non-ok HTTP response.
 */
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
    // Parse the error body if present; fall back to an empty object so callers
    // (and the integrator's auth handler) can still read `.status`.
    const info = await response.json().catch(() => ({}));
    throw new FetchError(
      `send-message${stream ? "" : " (one-shot)"} failed with status ${response.status}`,
      response.status,
      info
    );
  }

  return response;
}

/**
 * Stream a chat message. POSTs the request to `/api/chat/send-message` via the
 * platform fetch (expo/fetch on mobile), then yields each decoded NDJSON `Packet`.
 *
 * Cancellation: pass an `AbortSignal`. Aborting it cancels the underlying reader
 * inside `handleSSEStream`. Do NOT `break` out of the generator to cancel.
 *
 * @throws FetchError on a non-ok HTTP response (status + parsed body carried through).
 */
export async function* streamChatMessage(
  req: SendMessageRequest,
  config: ClientConfig,
  signal?: AbortSignal
): AsyncGenerator<Packet, void, unknown> {
  const response = await postSendMessage(req, config, true, signal);
  yield* handleSSEStream<Packet>(response, signal);
}
