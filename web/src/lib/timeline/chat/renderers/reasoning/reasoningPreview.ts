import { type Packet, PacketType } from "@/app/app/services/streamingModels";

const MAX_PREVIEW_LENGTH = 200;

/** The reasoning text a step's packets carry so far. */
export function reasoningText(packets: Packet[]): string {
  let text = "";
  for (const packet of packets) {
    if (packet.obj.type === PacketType.REASONING_DELTA) {
      text += packet.obj.reasoning;
    }
  }
  return text;
}

/**
 * A one-line preview of live reasoning: whitespace collapsed, and only the
 * latest text when it is long. Empty when there is no text yet.
 */
export function reasoningPreview(text: string): string {
  const line = text.trim().replace(/\s+/g, " ");
  return line.length > MAX_PREVIEW_LENGTH
    ? `…${line.slice(-MAX_PREVIEW_LENGTH).trimStart()}`
    : line;
}
