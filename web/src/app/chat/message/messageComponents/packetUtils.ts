import {
  MessageDelta,
  MessageStart,
  PacketType,
} from "../../services/streamingModels";
import { Packet } from "@/app/chat/services/streamingModels";

export function isToolPacket(packet: Packet) {
  return (
    packet.obj.type === PacketType.TOOL_START ||
    packet.obj.type === PacketType.TOOL_DELTA ||
    packet.obj.type === PacketType.TOOL_END
  );
}

export function isStreamingComplete(packets: Packet[]) {
  return packets.some((packet) => packet.obj.type === PacketType.STOP);
}

export function isFinalAnswerComing(packets: Packet[]) {
  return packets.some((packet) => packet.obj.type === PacketType.MESSAGE_START);
}

export function isFinalAnswerComplete(packets: Packet[]) {
  return packets.some((packet) => packet.obj.type === PacketType.MESSAGE_END);
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
