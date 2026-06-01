// packetUtils.ts — pure packet classifiers + content extraction.
//
// Mirrors web packetUtils.ts.
// Only the helpers the timeline pipeline needs. Mobile's PacketType enum
// (src/lib/types/streaming.ts) mirrors the backend, so these port verbatim.

import { Packet, PacketType } from "@/lib/types";

export function isToolPacket(
  packet: Packet,
  includeSectionEnd: boolean = true
): boolean {
  const toolPacketTypes: PacketType[] = [
    PacketType.SEARCH_TOOL_START,
    PacketType.SEARCH_TOOL_QUERIES_DELTA,
    PacketType.SEARCH_TOOL_DOCUMENTS_DELTA,
    PacketType.PYTHON_TOOL_START,
    PacketType.PYTHON_TOOL_DELTA,
    PacketType.TOOL_CALL_ARGUMENT_DELTA,
    PacketType.CUSTOM_TOOL_START,
    PacketType.CUSTOM_TOOL_ARGS,
    PacketType.CUSTOM_TOOL_DELTA,
    PacketType.FILE_READER_START,
    PacketType.FILE_READER_RESULT,
    PacketType.REASONING_START,
    PacketType.REASONING_DELTA,
    PacketType.FETCH_TOOL_START,
    PacketType.FETCH_TOOL_URLS,
    PacketType.FETCH_TOOL_DOCUMENTS,
    PacketType.MEMORY_TOOL_START,
    PacketType.MEMORY_TOOL_DELTA,
    PacketType.MEMORY_TOOL_NO_ACCESS,
    PacketType.DEEP_RESEARCH_PLAN_START,
    PacketType.DEEP_RESEARCH_PLAN_DELTA,
    PacketType.RESEARCH_AGENT_START,
    PacketType.INTERMEDIATE_REPORT_START,
    PacketType.INTERMEDIATE_REPORT_DELTA,
    PacketType.INTERMEDIATE_REPORT_CITED_DOCS,
    PacketType.CODING_AGENT_START,
    PacketType.CODING_AGENT_THINKING_DELTA,
    PacketType.CODING_AGENT_FINAL,
    PacketType.BASH_TOOL_START,
    PacketType.BASH_TOOL_DELTA,
  ];
  if (includeSectionEnd) {
    toolPacketTypes.push(PacketType.SECTION_END);
    toolPacketTypes.push(PacketType.ERROR);
  }
  return toolPacketTypes.includes(packet.obj.type as PacketType);
}

// An "actual" tool call (not reasoning) — used to reset finalAnswerComing when
// a tool starts after message packets (Claude workaround). Reasoning is just
// thinking, not a content-producing tool call.
export function isActualToolCallPacket(packet: Packet): boolean {
  return (
    isToolPacket(packet, false) &&
    packet.obj.type !== PacketType.REASONING_START &&
    packet.obj.type !== PacketType.REASONING_DELTA
  );
}

export function isDisplayPacket(packet: Packet): boolean {
  return (
    packet.obj.type === PacketType.MESSAGE_START ||
    packet.obj.type === PacketType.IMAGE_GENERATION_TOOL_START
  );
}

export function isFinalAnswerComplete(packets: Packet[]): boolean {
  const messageStartPacket = packets.find(
    (packet) =>
      packet.obj.type === PacketType.MESSAGE_START ||
      packet.obj.type === PacketType.IMAGE_GENERATION_TOOL_START
  );

  if (!messageStartPacket) {
    return false;
  }

  return packets.some(
    (packet) =>
      (packet.obj.type === PacketType.SECTION_END ||
        packet.obj.type === PacketType.ERROR) &&
      packet.placement.turn_index === messageStartPacket.placement.turn_index
  );
}
