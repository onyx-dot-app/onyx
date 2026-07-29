// Reveals concatenated stream content at a steady pace (useTypewriter) so bursty responses still animate in.
import { useMemo, useState } from "react";

import {
  MessageDelta,
  MessageStart,
  Packet,
  PacketType,
} from "@/chat/streamingModels";
import { openUrl } from "@/chat/openSource";
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
      // message_start can arrive with no content; guard prevents appending literal "undefined".
      content += (packet.obj as MessageStart | MessageDelta).content ?? "";
    }
  }
  return content;
}

function MessageText({ packets, processed }: MessageRendererProps) {
  const isComplete = processed.isComplete;
  // Stable across packet flushes so the typewriter target grows only when content does.
  const content = useMemo(() => accumulateContent(packets), [packets]);
  // Captured once at mount: live messages animate; historical ones mount complete and snap.
  const [animate] = useState(() => !isComplete);
  const { displayed } = useTypewriter(content, animate, isComplete);
  return (
    <StreamingMarkdown
      content={displayed}
      isStreaming={!isComplete}
      onLinkPress={openUrl}
    />
  );
}

export const MessageTextRenderer: MessageRenderer = {
  matches: (packets) => packets.some(isChatPacket),
  Component: MessageText,
};
