// Priority-ordered renderer dispatch, mirroring web `renderMessageComponent`. First match wins. Only the
// chat slot is wired in 9b.4; each tool slot below is a one-line wire-up in a later phase — the ordering
// is already baked in so those phases never touch the priority logic.
import { Packet, PacketType } from "@/chat/streamingModels";

import { MessageTextRenderer } from "./MessageTextRenderer";
import type { DispatchRenderer } from "./timelineContract";

function isChatPacket(packet: Packet): boolean {
  return (
    packet.obj.type === PacketType.MESSAGE_START ||
    packet.obj.type === PacketType.MESSAGE_DELTA ||
    packet.obj.type === PacketType.MESSAGE_END
  );
}

// A reasoning group is closed by a section_end (or error), so those types fall to it once the
// higher-priority slots above have had their turn.
function isReasoningPacket(packet: Packet): boolean {
  return (
    packet.obj.type === PacketType.REASONING_START ||
    packet.obj.type === PacketType.REASONING_DELTA ||
    packet.obj.type === PacketType.SECTION_END ||
    packet.obj.type === PacketType.ERROR
  );
}

export function findRenderer(packets: Packet[]): DispatchRenderer | null {
  if (packets.some(isChatPacket)) {
    return MessageTextRenderer;
  }

  // Tool renderers land in follow-up phases, in web's priority order:
  //   deep-research plan → research-agent → coding-agent          // PR 9x
  //   web-search → internal-search                                 // PR 9x
  //   image → python → file-reader → custom-tool → fetch → memory  // PR 9x

  // Reasoning is wired in 9b.6; the slot is present (returns null) so the priority ordering is correct.
  if (packets.some(isReasoningPacket)) {
    return null;
  }

  return null;
}
