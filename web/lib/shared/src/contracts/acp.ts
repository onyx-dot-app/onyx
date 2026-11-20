export interface ChatToolUpdate {
  toolCallId: string;
  status?: "pending" | "in_progress" | "completed" | "failed";
}

/** The parent call owns the step. A nested call can finish independently. */
export function latestToolStatus(
  packets: readonly {
    placement: { sub_turn_index?: number | null };
    acpTool?: ChatToolUpdate;
  }[]
): ChatToolUpdate["status"] {
  for (let i = packets.length - 1; i >= 0; i--) {
    const packet = packets[i];
    if (
      packet &&
      packet.placement.sub_turn_index == null &&
      packet.acpTool?.status
    ) {
      return packet.acpTool.status;
    }
  }
  return undefined;
}

// First-party clients use these notifications for both live chat and replay.
// The session's stored view uses the same display objects as the renderer.
function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function readChatNotification(
  // oxlint-disable-next-line anti-slop/no-unknown-parameters -- Validates the incoming JSON-RPC object.
  frame: unknown,
  sessionId: string
): object | null {
  if (!isObject(frame)) throw new Error("Invalid chat stream record");
  // Self-hosted servers predating protocol_version return v1 display packets and controls.
  if (
    !("jsonrpc" in frame) &&
    !("method" in frame) &&
    ((isObject(frame.placement) && isObject(frame.obj)) ||
      "user_message_id" in frame ||
      "next_cursor" in frame ||
      "chat_session_id" in frame ||
      typeof frame.error === "string")
  ) {
    return frame;
  }
  if (frame.jsonrpc !== "2.0" || !isObject(frame.params)) {
    throw new Error("Invalid ACP chat notification");
  }
  const { method, params } = frame;
  if (params.sessionId !== sessionId) throw new Error("Unexpected ACP session");
  if (typeof method === "string" && method.startsWith("_onyx/")) {
    return isObject(params.packet) ? params.packet : null;
  }
  if (method !== "session/update") return null;
  const update = params.update;
  if (!isObject(update)) throw new Error("Invalid ACP session update");
  const meta = isObject(update._meta) ? update._meta.onyx : undefined;
  if (!isObject(meta) || !isObject(meta.placement)) return null;
  const placement = meta.placement;
  const result = update.rawOutput;
  const packet =
    isObject(result) && typeof result.type === "string" ? result : meta.packet;
  if (isObject(packet)) {
    return {
      placement,
      obj: packet,
      ...(typeof update.toolCallId === "string" && {
        acpTool: { toolCallId: update.toolCallId, status: update.status },
      }),
    };
  }
  const content = update.content;
  if (
    !isObject(content) ||
    content.type !== "text" ||
    typeof content.text !== "string"
  ) {
    return null;
  }
  switch (update.sessionUpdate) {
    case "user_message_chunk": {
      const source = meta.userMessage;
      if (!isObject(source)) return null;
      return {
        placement,
        obj: {
          type: "user_message",
          id: source.id,
          mentions: source.mentions,
          message: content.text,
        },
      };
    }
    case "agent_message_chunk":
      return {
        placement,
        obj: { type: "message_delta", content: content.text },
      };
    case "agent_thought_chunk":
      return {
        placement,
        obj: { type: "reasoning_delta", reasoning: content.text },
      };
    default:
      return null;
  }
}

/** Read one first-party ACP notification per NDJSON line. */
export async function* readChatNotifications(
  sessionId: string,
  body: Pick<ReadableStream<Uint8Array>, "getReader"> | null,
  signal?: AbortSignal
): AsyncGenerator<object> {
  const reader = body?.getReader();
  if (!reader) throw new Error("Chat stream has no body");
  const abort = () => void reader.cancel().catch(() => {});
  signal?.addEventListener("abort", abort, { once: true });
  const decoder = new TextDecoder();
  // A long record can span many reads. Join its fragments once when the line ends.
  const fragments: string[] = [];
  try {
    while (!signal?.aborted) {
      const { value, done } = await reader.read();
      if (signal?.aborted) break;
      const chunk = done
        ? decoder.decode() + "\n"
        : decoder.decode(value, { stream: true });
      let start = 0;
      while (start < chunk.length) {
        const end = chunk.indexOf("\n", start);
        if (end === -1) {
          fragments.push(chunk.slice(start));
          break;
        }
        const tail = chunk.slice(start, end);
        const line = fragments.length ? fragments.join("") + tail : tail;
        fragments.length = 0;
        if (line.trim()) {
          const packet = readChatNotification(JSON.parse(line), sessionId);
          if (packet) yield packet;
        }
        start = end + 1;
      }
      if (done) break;
    }
  } finally {
    signal?.removeEventListener("abort", abort);
    void reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

export type WireChatHistory<Page> = Omit<Page, "packets"> & {
  packets: unknown[][];
};

/** Saved history preserves one packet list per assistant message, including empty replies. */
export function readChatHistory<T extends { packets: unknown[][] }>(
  sessionId: string,
  page: WireChatHistory<T>
): T {
  // SAFETY: Each notification decodes to the display packet used by the client's session type.
  return {
    ...page,
    packets: page.packets.map((frames) => {
      const packets = [];
      for (const frame of frames) {
        const packet = readChatNotification(frame, sessionId);
        if (packet) packets.push(packet);
      }
      return packets;
    }),
  } as T;
}
