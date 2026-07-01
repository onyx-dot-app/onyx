// MESSAGE_START/DELTA content concatenated into one markdown string.
import {
  MessageDelta,
  MessageStart,
  Packet,
  PacketType,
} from "@/chat/streamingModels";
import { StreamingMarkdown } from "@/components/chat/StreamingMarkdown";

import type { MessageRenderer, MessageRendererProps } from "./registry";

function isChatPacket(packet: Packet): boolean {
  return (
    packet.obj.type === PacketType.MESSAGE_START ||
    packet.obj.type === PacketType.MESSAGE_DELTA ||
    packet.obj.type === PacketType.MESSAGE_END
  );
}

function accumulateContent(packets: Packet[]): string {
  let content = "";
  for (const packet of packets) {
    if (
      packet.obj.type === PacketType.MESSAGE_START ||
      packet.obj.type === PacketType.MESSAGE_DELTA
    ) {
      content += (packet.obj as MessageStart | MessageDelta).content;
    }
  }
  return content;
}

function MessageText({ packets, isComplete }: MessageRendererProps) {
  const content = accumulateContent(packets);
  return <StreamingMarkdown content={content} isStreaming={!isComplete} />;
}

export const MessageTextRenderer: MessageRenderer = {
  matches: (packets) => packets.some(isChatPacket),
  Component: MessageText,
};
