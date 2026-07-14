// MESSAGE_START/DELTA content concatenated into one markdown string, then revealed at a steady
// pace (useTypewriter) so a fast/bursty response still animates in like other AI chat apps.
import { useMemo, useState } from "react";

import {
  MessageDelta,
  MessageStart,
  Packet,
  PacketType,
} from "@/chat/streamingModels";
import { StreamingMarkdown } from "@/components/chat/StreamingMarkdown";
import { useTypewriter } from "@/hooks/useTypewriter";

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
      // `?? ""`: a message_start packet can arrive with no `content`; without the guard the
      // template appends the literal string "undefined" before the first delta.
      content += (packet.obj as MessageStart | MessageDelta).content ?? "";
    }
  }
  return content;
}

function MessageText({ packets, isComplete }: MessageRendererProps) {
  // Stable between packet flushes so the typewriter target only grows when content actually does.
  const content = useMemo(() => accumulateContent(packets), [packets]);
  // Captured once at mount: animate live messages; a hydrated/historical one mounts complete → snap.
  const [animate] = useState(() => !isComplete);
  const { displayed } = useTypewriter(content, animate, isComplete);
  return <StreamingMarkdown content={displayed} isStreaming={!isComplete} />;
}

export const MessageTextRenderer: MessageRenderer = {
  matches: (packets) => packets.some(isChatPacket),
  Component: MessageText,
};
