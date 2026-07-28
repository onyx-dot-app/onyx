// Pure, incremental packet -> state processor for one assistant message. A small mobile port of
// web's `packetProcessor`: it advances a cursor (`nextPacketIndex`), processes only NEW packets each
// call, and mutates its state in place. 9a fills it with citations + documents; 9b extends it with
// turn/tab grouping + timeline steps, so the shape here stays deliberately flat (grouping-free).

import {
  CitationMap,
  SearchDoc,
  StreamingCitation,
} from "@/chat/contracts/documents";
import {
  CitationInfo,
  MessageStart,
  OpenUrlDocuments,
  Packet,
  PacketType,
  SearchToolDocumentsDelta,
  Stop,
  StopReason,
} from "@/chat/streamingModels";

export interface ProcessedMessageState {
  nodeId: number;
  nextPacketIndex: number; // cursor — process only packets past this index
  citationMap: CitationMap;
  citations: StreamingCitation[]; // deduped, first-cite order
  seenCitationDocIds: Set<string>; // dedups `citations`
  documentMap: Map<string, SearchDoc>;
  isComplete: boolean; // saw MESSAGE_END or STOP
  stopReason?: StopReason;
}

export function createInitialState(nodeId: number): ProcessedMessageState {
  return {
    nodeId,
    nextPacketIndex: 0,
    citationMap: {},
    citations: [],
    seenCitationDocIds: new Set(),
    documentMap: new Map(),
    isComplete: false,
    stopReason: undefined,
  };
}

function upsertDocuments(
  state: ProcessedMessageState,
  documents: SearchDoc[],
): void {
  for (const doc of documents) {
    if (doc.document_id) state.documentMap.set(doc.document_id, doc);
  }
}

function processPacket(state: ProcessedMessageState, packet: Packet): void {
  const obj = packet.obj;
  switch (obj.type) {
    case PacketType.CITATION_INFO: {
      const citation = obj as CitationInfo;
      state.citationMap[citation.citation_number] = citation.document_id;
      if (!state.seenCitationDocIds.has(citation.document_id)) {
        state.seenCitationDocIds.add(citation.document_id);
        state.citations.push({
          citation_num: citation.citation_number,
          document_id: citation.document_id,
        });
      }
      break;
    }
    case PacketType.SEARCH_TOOL_DOCUMENTS_DELTA:
      upsertDocuments(state, (obj as SearchToolDocumentsDelta).documents ?? []);
      break;
    case PacketType.OPEN_URL_DOCUMENTS:
      upsertDocuments(state, (obj as OpenUrlDocuments).documents ?? []);
      break;
    case PacketType.MESSAGE_START: {
      const documents = (obj as MessageStart).final_documents;
      if (documents) upsertDocuments(state, documents);
      break;
    }
    case PacketType.MESSAGE_END:
      state.isComplete = true;
      break;
    case PacketType.STOP:
      state.isComplete = true;
      state.stopReason = (obj as Stop).stop_reason;
      break;
    default:
      break; // message_delta / section_end / error / heartbeat: not our concern
  }
}

export function processPackets(
  state: ProcessedMessageState,
  rawPackets: Packet[],
): ProcessedMessageState {
  // Array replaced by a shorter list (regenerate / history reload) -> rebuild from scratch so we
  // never double-count a re-streamed turn.
  if (state.nextPacketIndex > rawPackets.length) {
    state = createInitialState(state.nodeId);
  }
  for (let i = state.nextPacketIndex; i < rawPackets.length; i++) {
    const packet = rawPackets[i];
    if (packet) processPacket(state, packet);
  }
  state.nextPacketIndex = rawPackets.length;
  return state;
}
