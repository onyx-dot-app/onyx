import {
  Packet,
  StreamingCitation,
  StopReason,
  ResponseItem,
} from "@/app/app/services/streamingModels";
import { CitationMap } from "@/app/app/interfaces";
import { OnyxDocument } from "@/lib/search/types";
import { ResponseItems } from "@/app/app/services/responseItems";

export interface GroupedItem {
  turn_index: number;
  tab_index: number;
  items: ResponseItem[];
}

export interface ProcessorState {
  nodeId: number;
  nextPacketIndex: number;
  response: ResponseItems;
  citations: StreamingCitation[];
  citationMap: CitationMap;
  documentMap: Map<string, OnyxDocument>;
  toolGroups: GroupedItem[];
  narrationGroups: GroupedItem[];
  potentialDisplayGroups: GroupedItem[];
  isGeneratingImage: boolean;
  generatedImageCount: number;
  finalAnswerComing: boolean;
  stopPacketSeen: boolean;
  stopReason: StopReason | undefined;
  toolProcessingDuration: number | undefined;
}

export function createInitialState(nodeId: number): ProcessorState {
  return {
    nodeId,
    nextPacketIndex: 0,
    response: new ResponseItems(),
    citations: [],
    citationMap: {},
    documentMap: new Map(),
    toolGroups: [],
    narrationGroups: [],
    potentialDisplayGroups: [],
    isGeneratingImage: false,
    generatedImageCount: 0,
    finalAnswerComing: false,
    stopPacketSeen: false,
    stopReason: undefined,
    toolProcessingDuration: undefined,
  };
}

export function processPackets(
  state: ProcessorState,
  packets: Packet[]
): ProcessorState {
  if (state.nextPacketIndex > packets.length)
    state = createInitialState(state.nodeId);
  if (state.nextPacketIndex === packets.length) return state;
  for (const packet of packets.slice(state.nextPacketIndex)) {
    state.response.apply(packet);
    if (packet.obj.type === "stop") {
      state.stopPacketSeen = true;
      state.stopReason = packet.obj.stop_reason ?? undefined;
    }
  }
  state.nextPacketIndex = packets.length;
  const groups = new Map<string, GroupedItem>();
  const citations = new Map<string, StreamingCitation>();
  state.citationMap = {};
  state.documentMap = new Map();
  state.isGeneratingImage = false;
  state.generatedImageCount = 0;
  state.finalAnswerComing = false;
  for (const item of state.response.items.values()) {
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
    const { turn_index, tab_index = 0 } = item.placement;
    const key = `${turn_index}-${tab_index}`;
    let group = groups.get(key);
    if (!group) {
      group = { turn_index, tab_index, items: [] };
      groups.set(key, group);
    }
    group.items.push(item);
    const content = item.content;
    if (content.kind === "text") {
      for (const citation of content.citations) {
        state.citationMap[citation.citation_number] = citation.document_id;
        citations.set(citation.document_id, {
          citation_num: citation.citation_number,
          document_id: citation.document_id,
        });
      }
      for (const doc of content.documents)
        state.documentMap.set(doc.document_id, doc);
      if (!item.identity.parent_run_id && content.purpose === "answer") {
        state.finalAnswerComing = true;
        state.toolProcessingDuration = content.pre_answer_seconds ?? undefined;
      }
    }
    if (content.kind === "tool" && content.metadata?.type === "search_result") {
      for (const doc of content.metadata.displayed_docs ??
        content.metadata.search_docs)
        state.documentMap.set(doc.document_id, doc);
    }
    if (content.kind === "tool" && content.name === "generate_image") {
      state.isGeneratingImage ||=
        content.status === "running" || content.status === "pending";
      state.generatedImageCount +=
        content.metadata?.type === "image_generation_result"
          ? content.metadata.generated_images.length
          : 0;
      state.finalAnswerComing = true;
    }
  }
  state.citations = [...citations.values()];
  const sorted = [...groups.values()].sort(
    (a, b) => a.turn_index - b.turn_index || a.tab_index - b.tab_index
  );
  state.potentialDisplayGroups = sorted.filter((group) =>
    group.items.some(
      (item) =>
        !item.identity.parent_run_id &&
        ((item.content.kind === "text" && item.content.purpose === "answer") ||
          (item.content.kind === "tool" &&
            item.content.name === "generate_image"))
    )
  );
  state.narrationGroups = sorted.filter((group) =>
    group.items.some(
      (item) =>
        !item.identity.parent_run_id &&
        item.content.kind === "text" &&
        item.content.purpose === "commentary"
    )
  );
  const display = new Set([
    ...state.potentialDisplayGroups,
    ...state.narrationGroups,
  ]);
  state.toolGroups = sorted.filter((group) => !display.has(group));
  return state;
}
