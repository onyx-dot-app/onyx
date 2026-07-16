// Pure packet categorizers + turn/tab grouping helpers. Faithful port of web's
// `web/src/app/app/services/packetUtils.ts` (mobile imports only).

import {
  MessageDelta,
  MessageStart,
  Packet,
  PacketType,
  StreamingCitation,
} from "@/chat/streamingModels";

export function isToolPacket(
  packet: Packet,
  includeSectionEnd: boolean = true,
): boolean {
  const toolPacketTypes: PacketType[] = [
    PacketType.SEARCH_TOOL_START,
    PacketType.SEARCH_TOOL_QUERIES_DELTA,
    PacketType.SEARCH_TOOL_FILTER_DELTA,
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

// An actual tool call (not reasoning/thinking). Used to decide whether to reset
// `finalAnswerComing` when a tool packet arrives after message packets (Claude workaround).
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

export function isSearchToolPacket(packet: Packet): boolean {
  return (
    packet.obj.type === PacketType.SEARCH_TOOL_START ||
    packet.obj.type === PacketType.SEARCH_TOOL_QUERIES_DELTA ||
    packet.obj.type === PacketType.SEARCH_TOOL_FILTER_DELTA ||
    packet.obj.type === PacketType.SEARCH_TOOL_DOCUMENTS_DELTA
  );
}

export function isStreamingComplete(packets: Packet[]): boolean {
  return packets.some((packet) => packet.obj.type === PacketType.STOP);
}

export function isFinalAnswerComing(packets: Packet[]): boolean {
  return packets.some(
    (packet) =>
      packet.obj.type === PacketType.MESSAGE_START ||
      packet.obj.type === PacketType.IMAGE_GENERATION_TOOL_START,
  );
}

export function isFinalAnswerComplete(packets: Packet[]): boolean {
  const messageStartPacket = packets.find(
    (packet) =>
      packet.obj.type === PacketType.MESSAGE_START ||
      packet.obj.type === PacketType.IMAGE_GENERATION_TOOL_START,
  );

  if (!messageStartPacket) {
    return false;
  }

  return packets.some(
    (packet) =>
      (packet.obj.type === PacketType.SECTION_END ||
        packet.obj.type === PacketType.ERROR) &&
      packet.placement.turn_index === messageStartPacket.placement.turn_index,
  );
}

// Group packets by (turn_index, tab_index), ordered lowest→highest turn then tab. Supports
// parallel tool calls (same turn_index, different tab_index).
export function groupPacketsByTurnIndex(
  packets: Packet[],
): { turn_index: number; tab_index: number; packets: Packet[] }[] {
  const groups = packets.reduce(
    (
      acc: Map<
        string,
        { turn_index: number; tab_index: number; packets: Packet[] }
      >,
      packet,
    ) => {
      const turn_index = packet.placement.turn_index;
      const tab_index = packet.placement.tab_index ?? 0;
      const key = `${turn_index}-${tab_index}`;
      if (!acc.has(key)) {
        acc.set(key, { turn_index, tab_index, packets: [] });
      }
      acc.get(key)!.packets.push(packet);
      return acc;
    },
    new Map(),
  );

  return Array.from(groups.values()).sort((a, b) => {
    if (a.turn_index !== b.turn_index) {
      return a.turn_index - b.turn_index;
    }
    return a.tab_index - b.tab_index;
  });
}

export function getTextContent(packets: Packet[]): string {
  return packets
    .map((packet) => {
      if (
        packet.obj.type === PacketType.MESSAGE_START ||
        packet.obj.type === PacketType.MESSAGE_DELTA
      ) {
        return (packet.obj as MessageStart | MessageDelta).content || "";
      }
      return "";
    })
    .join("");
}

export function getCitations(packets: Packet[]): StreamingCitation[] {
  const citations: StreamingCitation[] = [];
  const seenDocIds = new Set<string>();

  packets.forEach((packet) => {
    if (packet.obj.type === PacketType.CITATION_INFO) {
      const citationInfo = packet.obj as {
        citation_number: number;
        document_id: string;
      };
      if (!seenDocIds.has(citationInfo.document_id)) {
        seenDocIds.add(citationInfo.document_id);
        citations.push({
          citation_num: citationInfo.citation_number,
          document_id: citationInfo.document_id,
        });
      }
    }
  });

  return citations;
}
