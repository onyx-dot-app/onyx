// The one place that bypasses apiFetch: only expo/fetch exposes a readable response.body on RN.
import { fetch as expoFetch } from "expo/fetch";
import { readChatNotifications } from "@onyx-ai/shared/acp";

import { getBaseUrl } from "@/api/config";
import { buildHeaders } from "@/api/client";
import { FileDescriptor } from "@/chat/interfaces";
import { LlmOverride } from "@/chat/models";
import { InternalSearchFilters } from "@/chat/sources";
import type { ToolOptionsEntry } from "@/chat/tools";
import {
  MessageResponseIDInfo,
  Packet,
  StreamingError,
} from "@/chat/streamingModels";

type ExpoResponse = Awaited<ReturnType<typeof expoFetch>>;

export interface SendMessageBody {
  message: string;
  chat_session_id: string;
  // null = first message; else the last assistant message id.
  parent_message_id: number | null;
  file_descriptors: FileDescriptor[];
  deep_research: boolean;
  origin: string;
  // Omitted/null = backend defaults: allow all tools and plugins, prefer none, no source filter.
  tool_options?: {
    allowed: ToolOptionsEntry[] | null;
    preferred: { type: "capability"; tool_id: number } | null;
    internal_search_filters: InternalSearchFilters | null;
  } | null;
  // Omitted or null runs the agent's own default model. Note the singular name: `llm_overrides`
  // is a separate field for multi-model comparison, which mobile does not use.
  llm_override?: LlmOverride | null;
}

export interface ChatToolOptions {
  deepResearch: boolean;
  allowed: ToolOptionsEntry[] | null;
  preferredToolId: number | null;
  internalSearchFilters: InternalSearchFilters | null;
  llmOverride: LlmOverride | null;
}

// status lets the resume caller stay silent on the expected "nothing to resume" (404).
export class StreamHttpError extends Error {
  constructor(
    message: string,
    readonly status: number,
    // Backend `error_code`, e.g. APPROVAL_PENDING.
    readonly code: string | null = null,
  ) {
    super(message);
    this.name = "StreamHttpError";
  }
}

// Follows the complete packet prefix of a resumed stream. Resuming from `next_cursor` delivers no
// packet twice. `replay_complete` marks the end of the output that existed when the resume began.
export interface StreamCursor {
  stream_id: number;
  next_cursor: number;
  replay_complete: boolean;
}

// The decoder yields placed display packets and session controls.
export type StreamEvent =
  Packet | MessageResponseIDInfo | StreamingError | StreamCursor;

export function isPacket(event: StreamEvent): event is Packet {
  return "obj" in event && "placement" in event;
}

export function isMessageIdInfo(
  event: StreamEvent,
): event is MessageResponseIDInfo {
  return "user_message_id" in event;
}

export function isStreamCursor(event: StreamEvent): event is StreamCursor {
  return "next_cursor" in event;
}

export function isStreamError(event: StreamEvent): event is StreamingError {
  return (
    "error" in event && typeof (event as StreamingError).error === "string"
  );
}

export function isHeartbeat(event: unknown): boolean {
  if (typeof event !== "object" || event === null) return true;
  const wrapped = (event as { obj?: { type?: string } }).obj;
  if (wrapped?.type === "chat_heartbeat") return true;
  return (event as { type?: string }).type === "chat_heartbeat";
}

async function raiseForStatus(response: ExpoResponse): Promise<never> {
  let detail = `Request failed with status ${response.status}`;
  let code: string | null = null;
  try {
    const parsed = JSON.parse(await response.text()) as {
      detail?: unknown;
      error_code?: unknown;
    };
    if (typeof parsed.detail === "string") detail = parsed.detail;
    if (typeof parsed.error_code === "string") code = parsed.error_code;
  } catch {
    // non-JSON body — keep the status message
  }
  throw new StreamHttpError(detail, response.status, code);
}

export async function* streamChatMessage(
  body: SendMessageBody,
  signal: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const response = await expoFetch(`${getBaseUrl()}/chat/send-chat-message`, {
    method: "POST",
    headers: await buildHeaders({ signal }, true),
    body: JSON.stringify({ ...body, protocol_version: 2 }),
    signal,
  });

  if (!response.ok) await raiseForStatus(response);
  for await (const item of readChatNotifications(
    body.chat_session_id,
    response.body,
    signal,
  )) {
    if (!isHeartbeat(item)) yield item as StreamEvent;
  }
}

// Replays stream `streamId` from `cursor` (0 = whole buffer), then tails it live. 404 when that
// stream has no buffer.
export async function* resumeChatMessage(
  sessionId: string,
  streamId: number,
  cursor: number,
  signal: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const response = await expoFetch(
    `${getBaseUrl()}/chat/chat-session/${sessionId}/resume-stream?stream_id=${streamId}&cursor=${cursor}&protocol_version=2`,
    { method: "GET", headers: await buildHeaders({ signal }, false), signal },
  );

  if (!response.ok) await raiseForStatus(response);
  for await (const item of readChatNotifications(
    sessionId,
    response.body,
    signal,
  )) {
    yield item as StreamEvent;
  }
}
