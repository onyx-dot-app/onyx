import {
  MessageDelta,
  MessageStart,
  PacketType,
  StreamingCitation,
} from "./streamingModels";
import { Packet } from "@/app/chat/services/streamingModels";

export function isToolPacket(
  packet: Packet,
  includeSectionEnd: boolean = true
) {
  let toolPacketTypes = [
    PacketType.SEARCH_TOOL_START,
    PacketType.SEARCH_TOOL_QUERIES_DELTA,
    PacketType.SEARCH_TOOL_DOCUMENTS_DELTA,
    PacketType.PYTHON_TOOL_START,
    PacketType.PYTHON_TOOL_DELTA,
    PacketType.CUSTOM_TOOL_START,
    PacketType.CUSTOM_TOOL_DELTA,
    PacketType.REASONING_START,
    PacketType.REASONING_DELTA,
    PacketType.FETCH_TOOL_START,
    PacketType.FETCH_TOOL_URLS,
    PacketType.FETCH_TOOL_DOCUMENTS,
    PacketType.DEEP_RESEARCH_PLAN_START,
    PacketType.DEEP_RESEARCH_PLAN_DELTA,
    PacketType.RESEARCH_AGENT_START,
    PacketType.INTERMEDIATE_REPORT_START,
    PacketType.INTERMEDIATE_REPORT_DELTA,
    PacketType.INTERMEDIATE_REPORT_CITED_DOCS,
  ];
  if (includeSectionEnd) {
    toolPacketTypes.push(PacketType.SECTION_END);
    toolPacketTypes.push(PacketType.ERROR);
  }
  return toolPacketTypes.includes(packet.obj.type as PacketType);
}

// Check if a packet is an actual tool call (not reasoning/thinking).
// This is used to determine if we should reset finalAnswerComing state
// when a tool packet arrives after message packets (Claude workaround).
// Reasoning packets should NOT reset finalAnswerComing since they are
// just the model thinking, not actual tool calls that would produce new content.
export function isActualToolCallPacket(packet: Packet): boolean {
  return (
    isToolPacket(packet, false) &&
    packet.obj.type !== PacketType.REASONING_START &&
    packet.obj.type !== PacketType.REASONING_DELTA
  );
}

export function isDisplayPacket(packet: Packet) {
  return (
    packet.obj.type === PacketType.MESSAGE_START ||
    packet.obj.type === PacketType.IMAGE_GENERATION_TOOL_START ||
    packet.obj.type === PacketType.PYTHON_TOOL_START
  );
}

export function isSearchToolPacket(packet: Packet): boolean {
  return (
    packet.obj.type === PacketType.SEARCH_TOOL_START ||
    packet.obj.type === PacketType.SEARCH_TOOL_QUERIES_DELTA ||
    packet.obj.type === PacketType.SEARCH_TOOL_DOCUMENTS_DELTA
  );
}

export function isStreamingComplete(packets: Packet[]) {
  return packets.some((packet) => packet.obj.type === PacketType.STOP);
}

export function isFinalAnswerComing(packets: Packet[]) {
  return packets.some(
    (packet) =>
      packet.obj.type === PacketType.MESSAGE_START ||
      packet.obj.type === PacketType.IMAGE_GENERATION_TOOL_START ||
      packet.obj.type === PacketType.PYTHON_TOOL_START
  );
}

export function isFinalAnswerComplete(packets: Packet[]) {
  // Find the first MESSAGE_START packet and get its index
  const messageStartPacket = packets.find(
    (packet) =>
      packet.obj.type === PacketType.MESSAGE_START ||
      packet.obj.type === PacketType.IMAGE_GENERATION_TOOL_START ||
      packet.obj.type === PacketType.PYTHON_TOOL_START
  );

  if (!messageStartPacket) {
    return false;
  }

  // Check if there's a corresponding SECTION_END or ERROR with the same turn_index
  return packets.some(
    (packet) =>
      (packet.obj.type === PacketType.SECTION_END ||
        packet.obj.type === PacketType.ERROR) &&
      packet.placement.turn_index === messageStartPacket.placement.turn_index
  );
}

export function groupPacketsByTurnIndex(
  packets: Packet[]
): { turn_index: number; tab_index: number; packets: Packet[] }[] {
  /*
  Group packets by (turn_index, tab_index). 
  Ordered from lowest turn_index to highest, then by tab_index within each turn.
  This supports parallel tool calls where multiple tools share the same turn_index
  but have different tab_index values.
  */
  const groups = packets.reduce(
    (
      acc: Map<
        string,
        { turn_index: number; tab_index: number; packets: Packet[] }
      >,
      packet
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
    new Map()
  );

  // Convert to array and sort by turn_index first, then tab_index
  return Array.from(groups.values()).sort((a, b) => {
    if (a.turn_index !== b.turn_index) {
      return a.turn_index - b.turn_index;
    }
    return a.tab_index - b.tab_index;
  });
}

export function getTextContent(packets: Packet[]) {
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
      // Individual citation packet from backend
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
