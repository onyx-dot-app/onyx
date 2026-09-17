/** Build timeline groups and source references from current response items. */
import {
  CitationMap,
  SearchDoc,
  StreamingCitation,
} from "@/chat/contracts/documents";
import { Packet, ResponseItem, StopReason } from "@/chat/streamingModels";
import { ResponseItems } from "@/chat/responseItems";

export interface GroupedItem {
  turn_index: number;
  tab_index: number;
  items: ResponseItem[];
}
export interface ProcessedMessageState {
  nodeId: number;
  nextPacketIndex: number;
  responseItems: ResponseItems;
  citationMap: CitationMap;
  citations: StreamingCitation[];
  documentMap: Map<string, SearchDoc>;
  groupedItemsMap: Map<string, ResponseItem[]>;
  isGeneratingImage: boolean;
  generatedImageCount: number;
  finalAnswerComing: boolean;
  stopPacketSeen: boolean;
  isComplete: boolean;
  stopReason: StopReason | undefined;
  toolProcessingDuration: number | undefined;
  toolGroups: GroupedItem[];
  potentialDisplayGroups: GroupedItem[];
}
export function createInitialState(nodeId: number): ProcessedMessageState {
  return {
    nodeId,
    nextPacketIndex: 0,
    responseItems: new ResponseItems(),
    citationMap: {},
    citations: [],
    documentMap: new Map(),
    groupedItemsMap: new Map(),
    isGeneratingImage: false,
    generatedImageCount: 0,
    finalAnswerComing: false,
    stopPacketSeen: false,
    isComplete: false,
    stopReason: undefined,
    toolProcessingDuration: undefined,
    toolGroups: [],
    potentialDisplayGroups: [],
  };
}
export function processPackets(
  state: ProcessedMessageState,
  packets: Packet[],
): ProcessedMessageState {
  if (state.nextPacketIndex > packets.length)
    state = createInitialState(state.nodeId);
  if (state.nextPacketIndex === packets.length) return state;
  for (const packet of packets.slice(state.nextPacketIndex)) {
    state.responseItems.apply(packet);
    if (packet.obj.type === "stop") {
      state.stopPacketSeen = true;
      state.isComplete = true;
      state.stopReason = packet.obj.stop_reason ?? undefined;
    }
  }
  state.nextPacketIndex = packets.length;
  state.groupedItemsMap = new Map();
  state.citationMap = {};
  state.citations = [];
  state.documentMap = new Map();
  state.isGeneratingImage = false;
  state.generatedImageCount = 0;
  state.finalAnswerComing = false;
  for (const item of state.responseItems.items.values()) {
    if (
      item.content.kind !== "tool" &&
      item.content.status !== "running" &&
      !item.content.text
    )
      continue;
    if (
      item.content.kind === "tool" &&
      [
        "think_tool",
        "generate_plan",
        "generate_report",
        "generate_answer",
      ].includes(item.content.name)
    )
      continue;
    const key = `${item.placement.turn_index}-${item.placement.tab_index ?? 0}`;
    const group = state.groupedItemsMap.get(key) ?? [];
    group.push(item);
    state.groupedItemsMap.set(key, group);
    const content = item.content;
    if (content.kind === "text") {
      for (const doc of content.documents)
        state.documentMap.set(doc.document_id, doc);
      if (!item.identity.parent_run_id) {
        for (const citation of content.citations) {
          state.citationMap[citation.citation_number] = citation.document_id;
          if (
            !state.citations.some((c) => c.document_id === citation.document_id)
          )
            state.citations.push({
              citation_num: citation.citation_number,
              document_id: citation.document_id,
            });
        }
        if (content.purpose === "answer") {
          state.finalAnswerComing = true;
          state.toolProcessingDuration =
            content.pre_answer_seconds ?? undefined;
        }
      }
    }
    if (content.kind === "tool") {
      if (content.name === "generate_image") {
        state.isGeneratingImage ||=
          content.status === "running" || content.status === "pending";
        state.finalAnswerComing = true;
      }
      if (content.metadata?.type === "image_generation_result")
        state.generatedImageCount += content.metadata.generated_images.length;
      if (content.metadata?.type === "search_result")
        for (const doc of content.metadata.displayed_docs ??
          content.metadata.search_docs)
          state.documentMap.set(doc.document_id, doc);
    }
  }
  state.toolGroups = [];
  state.potentialDisplayGroups = [];
  for (const items of state.groupedItemsMap.values()) {
    const first = items[0];
    if (!first) continue;
    const group = {
      turn_index: first.placement.turn_index,
      tab_index: first.placement.tab_index ?? 0,
      items,
    };
    const content = first.content;
    if (
      !first.identity.parent_run_id &&
      ((content.kind === "text" && content.purpose === "answer") ||
        (content.kind === "tool" && content.name === "generate_image"))
    )
      state.potentialDisplayGroups.push(group);
    else state.toolGroups.push(group);
  }
  return state;
}
