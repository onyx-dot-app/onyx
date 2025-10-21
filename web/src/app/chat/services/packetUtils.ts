import {
  CitationDelta,
  MessageDelta,
  MessageStart,
  PacketType,
  SearchToolDelta,
  StreamingCitation,
} from "./streamingModels";
import { Packet } from "@/app/chat/services/streamingModels";
import { OnyxDocument } from "@/lib/search/interfaces";

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

export function parsePacketsFromText(text: string): {
  packets: Packet[];
  errors: string[];
} {
  const packets: Packet[] = [];
  const errors: string[] = [];
  const lines = text.split("\n").filter((line) => line.trim() !== "");

  lines.forEach((line, index) => {
    try {
      const parsed = JSON.parse(line);

      // Skip the initial metadata packet (user_message_id, reserved_assistant_message_id)
      if (
        parsed.user_message_id !== undefined ||
        parsed.reserved_assistant_message_id !== undefined
      ) {
        return;
      }

      // Check if it's a valid packet with ind and obj
      if (
        typeof parsed.ind === "number" &&
        parsed.obj &&
        typeof parsed.obj === "object"
      ) {
        packets.push(parsed as Packet);
      } else {
        errors.push(`Line ${index + 1}: Missing 'ind' or 'obj' field`);
      }
    } catch (e) {
      errors.push(
        `Line ${index + 1}: Invalid JSON - ${
          e instanceof Error ? e.message : String(e)
        }`
      );
    }
  });

  return { packets, errors };
}

/**
 * Processes new packets incrementally, extracting documents, citations, and grouped packets.
 * This is the core packet processing logic used by both AIMessage and debug tools.
 *
 * @param packets - All packets received so far
 * @param lastProcessedIndex - Index of the last processed packet
 * @param documentMap - Map of document_id to OnyxDocument (will be mutated)
 * @param citations - Array of citations (will be mutated)
 * @param seenCitationDocIds - Set of seen citation document IDs (will be mutated)
 * @param groupedPacketsMap - Map of ind to packets for that ind (will be mutated)
 * @returns The new lastProcessedIndex and grouped packets array
 */
export function processNewPackets(
  packets: Packet[],
  lastProcessedIndex: number,
  documentMap: Map<string, OnyxDocument>,
  citations: StreamingCitation[],
  seenCitationDocIds: Set<string>,
  groupedPacketsMap: Map<number, Packet[]>
): {
  lastProcessedIndex: number;
  groupedPackets: { ind: number; packets: Packet[] }[];
} {
  // Process only new packets since last time
  if (packets.length > lastProcessedIndex) {
    for (let i = lastProcessedIndex; i < packets.length; i++) {
      const packet = packets[i];
      if (!packet) continue;

      // Group packets by ind
      const existingGroup = groupedPacketsMap.get(packet.ind);
      if (existingGroup) {
        existingGroup.push(packet);
      } else {
        groupedPacketsMap.set(packet.ind, [packet]);
      }

      // Extract documents from search tool delta
      if (packet.obj.type === PacketType.SEARCH_TOOL_DELTA) {
        const toolDelta = packet.obj as SearchToolDelta;
        if (toolDelta.documents) {
          toolDelta.documents.forEach((doc) => {
            if (doc.document_id) {
              documentMap.set(doc.document_id, doc);
            }
          });
        }
      }

      // Extract documents from fetch tool start
      if (packet.obj.type === PacketType.FETCH_TOOL_START) {
        const toolStart = packet.obj as any;
        if (toolStart.documents) {
          toolStart.documents.forEach((doc: OnyxDocument) => {
            if (doc.document_id) {
              documentMap.set(doc.document_id, doc);
            }
          });
        }
      }

      // Extract documents from message start
      if (packet.obj.type === PacketType.MESSAGE_START) {
        const messageStart = packet.obj as any;
        if (messageStart.final_documents) {
          messageStart.final_documents.forEach((doc: OnyxDocument) => {
            if (doc.document_id) {
              documentMap.set(doc.document_id, doc);
            }
          });
        }
      }

      // Extract citations (deduplicated)
      if (packet.obj.type === PacketType.CITATION_DELTA) {
        const citationDelta = packet.obj as CitationDelta;
        if (citationDelta.citations) {
          for (const citation of citationDelta.citations) {
            if (!seenCitationDocIds.has(citation.document_id)) {
              seenCitationDocIds.add(citation.document_id);
              citations.push(citation);
            }
          }
        }
      }
    }

    lastProcessedIndex = packets.length;
  }

  // Rebuild the grouped packets array sorted by ind
  // Clone packet arrays to ensure referential changes
  const groupedPackets = Array.from(groupedPacketsMap.entries())
    .map(([ind, packets]) => ({ ind, packets: [...packets] }))
    .sort((a, b) => a.ind - b.ind);

  return { lastProcessedIndex, groupedPackets };
}
