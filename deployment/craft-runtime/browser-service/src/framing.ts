import type { Socket } from "node:net";

export const KIND_JSON = 1;
export const KIND_JPEG = 2;
export const MAX_FRAME_LENGTH = 16 * 1024 * 1024;

export type Message =
  | { readonly kind: typeof KIND_JSON; readonly value: Record<string, unknown> }
  | { readonly kind: typeof KIND_JPEG; readonly data: Buffer };

export const encodeFrame = (kind: number, payload: Buffer): Buffer => {
  const header = Buffer.alloc(5);
  header.writeUInt32BE(payload.length + 1, 0);
  header.writeUInt8(kind, 4);
  return Buffer.concat([header, payload]);
};

export const encodeJson = (value: unknown): Buffer =>
  encodeFrame(KIND_JSON, Buffer.from(JSON.stringify(value), "utf8"));

/** Splits a byte stream into messages. Throws on any bad message. */
export class FrameDecoder {
  private buffer: Buffer = Buffer.alloc(0);

  push(chunk: Buffer): Array<Message> {
    this.buffer = this.buffer.length === 0 ? chunk : Buffer.concat([this.buffer, chunk]);
    const messages: Array<Message> = [];
    while (this.buffer.length >= 4) {
      const length = this.buffer.readUInt32BE(0);
      if (length < 1 || length > MAX_FRAME_LENGTH) throw new Error(`Frame length ${length} is out of range.`);
      const end = 4 + length;
      if (this.buffer.length < end) break;
      const kind = this.buffer.readUInt8(4);
      const payload = this.buffer.subarray(5, end);
      this.buffer = this.buffer.subarray(end);
      if (kind === KIND_JSON) {
        let value: unknown;
        try {
          value = JSON.parse(payload.toString("utf8"));
        } catch {
          throw new Error("A JSON frame did not parse.");
        }
        if (typeof value !== "object" || value === null || Array.isArray(value))
          throw new Error("A JSON frame is not an object.");
        messages.push({ kind: KIND_JSON, value: value as Record<string, unknown> });
      } else if (kind === KIND_JPEG) {
        messages.push({ kind: KIND_JPEG, data: Buffer.from(payload) });
      } else {
        throw new Error(`Unknown frame kind ${kind}.`);
      }
    }
    return messages;
  }
}

/** Calls onMessage for each message; a framing error or a throwing handler destroys the socket. */
export const readMessages = (
  socket: Socket,
  onMessage: (message: Message) => void,
  onError: (error: Error) => void,
) => {
  const decoder = new FrameDecoder();
  socket.on("data", (chunk: Buffer) => {
    if (socket.destroyed) return;
    let messages: Array<Message>;
    try {
      messages = decoder.push(chunk);
    } catch (error) {
      onError(error instanceof Error ? error : new Error(String(error)));
      socket.destroy();
      return;
    }
    for (const message of messages) {
      if (socket.destroyed) return;
      try {
        onMessage(message);
      } catch (error) {
        onError(error instanceof Error ? error : new Error(String(error)));
        socket.destroy();
        return;
      }
    }
  });
};
