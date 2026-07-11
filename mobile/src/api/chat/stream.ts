// Streams /chat NDJSON. The one place that bypasses apiFetch: only expo/fetch exposes a readable
// response.body on RN. Send POST and resume GET share the same reader + framing.
import { fetch as expoFetch } from "expo/fetch";

import { getBaseUrl } from "@/api/config";
import { getToken } from "@/api/auth/tokenStore";
import { createNdjsonBuffer } from "@/chat/ndjson";
import { FileDescriptor } from "@/chat/interfaces";
import { MessageResponseIDInfo, Packet } from "@/chat/streamingModels";

type ExpoResponse = Awaited<ReturnType<typeof expoFetch>>;

export interface SendMessageBody {
  message: string;
  chat_session_id: string;
  // null = first message; else the last assistant message id.
  parent_message_id: number | null;
  file_descriptors: FileDescriptor[];
  deep_research: boolean;
  origin: string;
}

// status lets the resume caller stay silent on the expected "nothing to resume" (404).
export class StreamHttpError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "StreamHttpError";
  }
}

// The wire mixes wrapped packets ({placement, obj}) with root control objects; discriminate by field, not `type`.
export type StreamEvent = Packet | MessageResponseIDInfo;

export function isPacket(event: StreamEvent): event is Packet {
  return "obj" in event && "placement" in event;
}

export function isMessageIdInfo(
  event: StreamEvent,
): event is MessageResponseIDInfo {
  return "user_message_id" in event;
}

// Heartbeats come wrapped or at root; drop both.
export function isHeartbeat(event: unknown): boolean {
  if (typeof event !== "object" || event === null) return true;
  const wrapped = (event as { obj?: { type?: string } }).obj;
  if (wrapped?.type === "chat_heartbeat") return true;
  return (event as { type?: string }).type === "chat_heartbeat";
}

// Auth + Accept only. Content-Type is added by the send POST; the resume GET has no body.
async function authHeaders(): Promise<Record<string, string>> {
  const token = await getToken();
  const headers: Record<string, string> = { Accept: "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

async function raiseForStatus(response: ExpoResponse): Promise<never> {
  let detail = `Request failed with status ${response.status}`;
  try {
    const parsed = JSON.parse(await response.text()) as { detail?: string };
    if (typeof parsed.detail === "string") detail = parsed.detail;
  } catch {
    // non-JSON body — keep the status message
  }
  throw new StreamHttpError(detail, response.status);
}

// resume keeps heartbeats as quiet-phase liveness ticks (to re-check focus/abort); send drops them
async function* readNdjson(
  response: ExpoResponse,
  keepHeartbeats = false,
): AsyncGenerator<StreamEvent> {
  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error("Streaming is not supported on this device.");
  }

  const decoder = new TextDecoder();
  const buffer = createNdjsonBuffer<StreamEvent>();
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      for (const event of buffer.pushChunk(
        decoder.decode(value, { stream: true }),
      )) {
        if (keepHeartbeats || !isHeartbeat(event)) yield event;
      }
    }
    for (const event of buffer.flush()) {
      if (keepHeartbeats || !isHeartbeat(event)) yield event;
    }
  } finally {
    // Release the reader on early-return/abort, or the connection leaks.
    void reader.cancel().catch(() => {});
  }
}

export async function* streamChatMessage(
  body: SendMessageBody,
  signal: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const response = await expoFetch(`${getBaseUrl()}/chat/send-chat-message`, {
    method: "POST",
    headers: { ...(await authHeaders()), "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });

  if (!response.ok) await raiseForStatus(response);
  yield* readNdjson(response);
}

// Replays an in-flight run's buffer from `cursor` (0 = whole buffer, matching web), then tails live.
// A 404 means no resumable run — the caller falls back to the persisted snapshot.
export async function* resumeChatMessage(
  sessionId: string,
  cursor: number,
  signal: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const response = await expoFetch(
    `${getBaseUrl()}/chat/chat-session/${sessionId}/resume-stream?cursor=${cursor}`,
    { method: "GET", headers: await authHeaders(), signal },
  );

  if (!response.ok) await raiseForStatus(response);
  yield* readNdjson(response, true);
}
