// Streams /chat/send-chat-message NDJSON. The one call that bypasses apiFetch: only expo/fetch exposes a
// readable response.body on RN.
import { fetch as expoFetch } from "expo/fetch";

import { getBaseUrl } from "@/api/config";
import { getToken } from "@/api/auth/tokenStore";
import { createNdjsonBuffer } from "@/chat/ndjson";
import { FileDescriptor } from "@/chat/interfaces";
import { MessageResponseIDInfo, Packet } from "@/chat/streamingModels";

export interface SendMessageBody {
  message: string;
  chat_session_id: string;
  // null = first message; else the last assistant message id.
  parent_message_id: number | null;
  file_descriptors: FileDescriptor[];
  deep_research: boolean;
  origin: string;
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
function isHeartbeat(event: unknown): boolean {
  if (typeof event !== "object" || event === null) return true;
  const wrapped = (event as { obj?: { type?: string } }).obj;
  if (wrapped?.type === "chat_heartbeat") return true;
  return (event as { type?: string }).type === "chat_heartbeat";
}

export async function* streamChatMessage(
  body: SendMessageBody,
  signal: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const token = await getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "application/json",
  };
  if (token) headers.Authorization = `Bearer ${token}`;

  const response = await expoFetch(`${getBaseUrl()}/chat/send-chat-message`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    signal,
  });

  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`;
    try {
      const parsed = JSON.parse(await response.text()) as { detail?: string };
      if (typeof parsed.detail === "string") detail = parsed.detail;
    } catch {
      // non-JSON body — keep the status message
    }
    throw new Error(detail);
  }

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
        if (!isHeartbeat(event)) yield event;
      }
    }
    for (const event of buffer.flush()) {
      if (!isHeartbeat(event)) yield event;
    }
  } finally {
    // Release the reader on early-return/abort, or the connection leaks.
    void reader.cancel().catch(() => {});
  }
}
