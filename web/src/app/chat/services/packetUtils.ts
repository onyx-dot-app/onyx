import {
  CitationDelta,
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
    PacketType.SEARCH_TOOL_DELTA,
    PacketType.CUSTOM_TOOL_START,
    PacketType.CUSTOM_TOOL_DELTA,
    PacketType.REASONING_START,
    PacketType.REASONING_DELTA,
    PacketType.FETCH_TOOL_START,
  ];
  if (includeSectionEnd) {
    toolPacketTypes.push(PacketType.SECTION_END);
  }
  return toolPacketTypes.includes(packet.obj.type as PacketType);
}

export function isDisplayPacket(packet: Packet) {
  return (
    packet.obj.type === PacketType.MESSAGE_START ||
    packet.obj.type === PacketType.IMAGE_GENERATION_TOOL_START
  );
}

export function isStreamingComplete(packets: Packet[]) {
  return packets.some((packet) => packet.obj.type === PacketType.STOP);
}

export function isFinalAnswerComing(packets: Packet[]) {
  return packets.some(
    (packet) =>
      packet.obj.type === PacketType.MESSAGE_START ||
      packet.obj.type === PacketType.IMAGE_GENERATION_TOOL_START
  );
}

export function isFinalAnswerComplete(packets: Packet[]) {
  // Find the first MESSAGE_START packet and get its index
  const messageStartPacket = packets.find(
    (packet) =>
      packet.obj.type === PacketType.MESSAGE_START ||
      packet.obj.type === PacketType.IMAGE_GENERATION_TOOL_START
  );

  if (!messageStartPacket) {
    return false;
  }

  // Check if there's a corresponding SECTION_END with the same index
  return packets.some(
    (packet) =>
      packet.obj.type === PacketType.SECTION_END &&
      packet.ind === messageStartPacket.ind
  );
}

export function groupPacketsByInd(
  packets: Packet[]
): { ind: number; packets: Packet[] }[] {
  /*
  Group packets by ind. Ordered from lowest ind to highest ind.
  */
  const groups = packets.reduce((acc: Map<number, Packet[]>, packet) => {
    const ind = packet.ind;
    if (!acc.has(ind)) {
      acc.set(ind, []);
    }
    acc.get(ind)!.push(packet);
    return acc;
  }, new Map());

  // Convert to array and sort by ind (lowest to highest)
  return Array.from(groups.entries())
    .map(([ind, packets]) => ({
      ind,
      packets,
    }))
    .sort((a, b) => a.ind - b.ind);
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

  packets.forEach((packet) => {
    if (packet.obj.type === PacketType.CITATION_DELTA) {
      const citationDelta = packet.obj as CitationDelta;
      citations.push(...(citationDelta.citations || []));
    }
  });

  return citations;
}
