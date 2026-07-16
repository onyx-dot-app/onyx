// Pure, incremental packet -> state processor for one assistant message. A faithful mobile port of
// web's `packetProcessor` (web/.../timeline/hooks/packetProcessor.ts): it advances a cursor
// (`nextPacketIndex`), processes only NEW packets each call, and mutates its state in place. It both
// (a) keeps the 9a citation/document/completion tracking and (b) groups packets into timeline steps
// by `${turn_index}-${tab_index}`, synthesizing SECTION_END (on a new turn, or on stop) so a step
// reads as "complete". The owning hook holds the state instance stable and feeds the growing packet
// array; see `hooks/timeline/usePacketProcessor`.

import {
  CitationMap,
  SearchDoc,
  StreamingCitation,
} from "@/chat/contracts/documents";
import {
  CitationInfo,
  CODE_INTERPRETER_TOOL_TYPES,
  FetchToolDocuments,
  ImageGenerationToolDelta,
  MessageStart,
  Packet,
  PacketType,
  SearchToolDocumentsDelta,
  Stop,
  StopReason,
  ToolCallArgumentDelta,
  TopLevelBranching,
} from "@/chat/streamingModels";
import {
  isActualToolCallPacket,
  isDisplayPacket,
  isToolPacket,
} from "@/chat/timeline/packetUtils";
import { parseToolKey } from "@/chat/timeline/toolDisplay";

export interface ProcessedMessageState {
  nodeId: number;
  nextPacketIndex: number; // cursor — process only packets past this index

  // Citations (9a)
  citationMap: CitationMap;
  citations: StreamingCitation[]; // deduped, first-cite order
  seenCitationDocIds: Set<string>; // dedups `citations`

  // Documents (9a)
  documentMap: Map<string, SearchDoc>;

  // Packet grouping (9b)
  groupedPacketsMap: Map<string, Packet[]>;
  seenGroupKeys: Set<string>;
  groupKeysWithSectionEnd: Set<string>;
  expectedBranches: Map<number, number>;
  toolGroupKeys: Set<string>; // populated during processing
  displayGroupKeys: Set<string>;

  // Image generation status (9b)
  isGeneratingImage: boolean;
  generatedImageCount: number;

  // Streaming status (9b)
  finalAnswerComing: boolean;
  stopPacketSeen: boolean;
  isComplete: boolean; // saw MESSAGE_END or STOP (9a; drives CitedSources)
  stopReason: StopReason | undefined;
  toolProcessingDuration: number | undefined; // from MESSAGE_START.pre_answer_processing_seconds

  // Result arrays (rebuilt at the end of processPackets)
  toolGroups: GroupedPacket[];
  potentialDisplayGroups: GroupedPacket[];
}

export interface GroupedPacket {
  turn_index: number;
  tab_index: number;
  packets: Packet[];
}

export function createInitialState(nodeId: number): ProcessedMessageState {
  return {
    nodeId,
    nextPacketIndex: 0,
    citationMap: {},
    citations: [],
    seenCitationDocIds: new Set(),
    documentMap: new Map(),
    groupedPacketsMap: new Map(),
    seenGroupKeys: new Set(),
    groupKeysWithSectionEnd: new Set(),
    expectedBranches: new Map(),
    toolGroupKeys: new Set(),
    displayGroupKeys: new Set(),
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

// Grouping helpers
function getGroupKey(packet: Packet): string {
  const turnIndex = packet.placement.turn_index;
  const tabIndex = packet.placement.tab_index ?? 0;
  return `${turnIndex}-${tabIndex}`;
}

// Push a synthetic SECTION_END into a group so its renderer reads as complete. Idempotent. The
// synthetic packet omits sub_turn_index (=> parent-level), which is what research/coding completion
// checks expect.
function injectSectionEnd(
  state: ProcessedMessageState,
  groupKey: string,
): void {
  if (state.groupKeysWithSectionEnd.has(groupKey)) {
    return;
  }

  const { turn_index, tab_index } = parseToolKey(groupKey);
  const syntheticPacket: Packet = {
    placement: { turn_index, tab_index },
    obj: { type: PacketType.SECTION_END },
  };

  const existingGroup = state.groupedPacketsMap.get(groupKey);
  if (existingGroup) {
    existingGroup.push(syntheticPacket);
  }
  state.groupKeysWithSectionEnd.add(groupKey);
}

// Packet types that mean a group has meaningful content to display.
const CONTENT_PACKET_TYPES_SET = new Set<PacketType>([
  PacketType.MESSAGE_START,
  PacketType.SEARCH_TOOL_START,
  PacketType.IMAGE_GENERATION_TOOL_START,
  PacketType.PYTHON_TOOL_START,
  PacketType.TOOL_CALL_ARGUMENT_DELTA,
  PacketType.CUSTOM_TOOL_START,
  PacketType.FILE_READER_START,
  PacketType.FETCH_TOOL_START,
  PacketType.MEMORY_TOOL_START,
  PacketType.MEMORY_TOOL_NO_ACCESS,
  PacketType.REASONING_START,
  PacketType.DEEP_RESEARCH_PLAN_START,
  PacketType.RESEARCH_AGENT_START,
  PacketType.CODING_AGENT_START,
]);

function hasContentPackets(packets: Packet[]): boolean {
  return packets.some((packet) => {
    const type = packet.obj.type as PacketType;
    if (type === PacketType.TOOL_CALL_ARGUMENT_DELTA) {
      return (
        (packet.obj as ToolCallArgumentDelta).tool_type ===
        CODE_INTERPRETER_TOOL_TYPES.PYTHON
      );
    }
    return CONTENT_PACKET_TYPES_SET.has(type);
  });
}

// Packet types that indicate final answer content is coming.
const FINAL_ANSWER_PACKET_TYPES_SET = new Set<PacketType>([
  PacketType.MESSAGE_START,
  PacketType.MESSAGE_DELTA,
  PacketType.IMAGE_GENERATION_TOOL_START,
  PacketType.IMAGE_GENERATION_TOOL_DELTA,
]);

// Packet handlers
function handleTopLevelBranching(
  state: ProcessedMessageState,
  packet: Packet,
): void {
  const branchingPacket = packet.obj as TopLevelBranching;
  state.expectedBranches.set(
    packet.placement.turn_index,
    branchingPacket.num_parallel_branches,
  );
}

// The first packet of a brand-new turn_index closes every prior group that hasn't ended (a new
// tab_index within a seen turn does NOT trigger this).
function handleTurnTransition(
  state: ProcessedMessageState,
  packet: Packet,
): void {
  const currentTurnIndex = packet.placement.turn_index;

  const previousTurnIndices = new Set(
    Array.from(state.seenGroupKeys).map((key) => parseToolKey(key).turn_index),
  );

  const isNewTurnIndex = !previousTurnIndices.has(currentTurnIndex);

  if (isNewTurnIndex && state.seenGroupKeys.size > 0) {
    state.seenGroupKeys.forEach((prevGroupKey) => {
      if (!state.groupKeysWithSectionEnd.has(prevGroupKey)) {
        injectSectionEnd(state, prevGroupKey);
      }
    });
  }
}

function upsertDocuments(
  state: ProcessedMessageState,
  documents: SearchDoc[] | null | undefined,
): void {
  if (!documents) return;
  for (const doc of documents) {
    if (doc.document_id) {
      state.documentMap.set(doc.document_id, doc);
    }
  }
}

function handleCitationPacket(
  state: ProcessedMessageState,
  packet: Packet,
): void {
  if (packet.obj.type !== PacketType.CITATION_INFO) {
    return;
  }

  const citationInfo = packet.obj as CitationInfo;
  state.citationMap[citationInfo.citation_number] = citationInfo.document_id;

  if (!state.seenCitationDocIds.has(citationInfo.document_id)) {
    state.seenCitationDocIds.add(citationInfo.document_id);
    state.citations.push({
      citation_num: citationInfo.citation_number,
      document_id: citationInfo.document_id,
    });
  }
}

function handleDocumentPacket(
  state: ProcessedMessageState,
  packet: Packet,
): void {
  if (packet.obj.type === PacketType.SEARCH_TOOL_DOCUMENTS_DELTA) {
    upsertDocuments(state, (packet.obj as SearchToolDocumentsDelta).documents);
  } else if (packet.obj.type === PacketType.FETCH_TOOL_DOCUMENTS) {
    upsertDocuments(state, (packet.obj as FetchToolDocuments).documents);
  } else if (packet.obj.type === PacketType.MESSAGE_START) {
    // Authoritative cited-doc set for the turn (9a).
    upsertDocuments(state, (packet.obj as MessageStart).final_documents);
  }
}

function handleStreamingStatusPacket(
  state: ProcessedMessageState,
  packet: Packet,
): void {
  if (FINAL_ANSWER_PACKET_TYPES_SET.has(packet.obj.type as PacketType)) {
    state.finalAnswerComing = true;
  }

  if (packet.obj.type === PacketType.MESSAGE_START) {
    const messageStart = packet.obj as MessageStart;
    if (messageStart.pre_answer_processing_seconds !== undefined) {
      state.toolProcessingDuration = messageStart.pre_answer_processing_seconds;
    }
  }
}

function handleStopPacket(state: ProcessedMessageState, packet: Packet): void {
  if (packet.obj.type !== PacketType.STOP || state.stopPacketSeen) {
    return;
  }

  state.stopPacketSeen = true;
  state.isComplete = true;
  state.stopReason = (packet.obj as Stop).stop_reason;

  // Close every still-open group (this is why the final answer group gets its SECTION_END even
  // though the backend never sends one).
  state.seenGroupKeys.forEach((groupKey) => {
    if (!state.groupKeysWithSectionEnd.has(groupKey)) {
      injectSectionEnd(state, groupKey);
    }
  });
}

// Claude can emit a message then start a real (non-reasoning) tool — the answer isn't actually
// coming yet, so un-set finalAnswerComing. Reasoning packets are excluded (just thinking).
function handleToolAfterMessagePacket(
  state: ProcessedMessageState,
  packet: Packet,
): void {
  if (
    state.finalAnswerComing &&
    !state.stopPacketSeen &&
    isActualToolCallPacket(packet)
  ) {
    state.finalAnswerComing = false;
  }
}

function addPacketToGroup(
  state: ProcessedMessageState,
  packet: Packet,
  groupKey: string,
): void {
  const existingGroup = state.groupedPacketsMap.get(groupKey);
  if (existingGroup) {
    existingGroup.push(packet);
  } else {
    state.groupedPacketsMap.set(groupKey, [packet]);
  }
}

// Main processing
function processPacket(state: ProcessedMessageState, packet: Packet): void {
  if (!packet) return;

  // TopLevelBranching is pure metadata — record expected branches, don't add to any group.
  if (packet.obj.type === PacketType.TOP_LEVEL_BRANCHING) {
    handleTopLevelBranching(state, packet);
    return;
  }

  handleTurnTransition(state, packet);

  const groupKey = getGroupKey(packet);
  state.seenGroupKeys.add(groupKey);

  // A real SECTION_END or ERROR marks the group complete.
  if (
    packet.obj.type === PacketType.SECTION_END ||
    packet.obj.type === PacketType.ERROR
  ) {
    state.groupKeysWithSectionEnd.add(groupKey);
  }

  const isFirstPacket = !state.groupedPacketsMap.get(groupKey);
  addPacketToGroup(state, packet, groupKey);

  if (isFirstPacket) {
    if (isToolPacket(packet, false)) {
      state.toolGroupKeys.add(groupKey);
    }
    if (isDisplayPacket(packet)) {
      state.displayGroupKeys.add(groupKey);
    }
  }

  if (packet.obj.type === PacketType.IMAGE_GENERATION_TOOL_START) {
    state.isGeneratingImage = true;
  }
  if (packet.obj.type === PacketType.IMAGE_GENERATION_TOOL_DELTA) {
    const delta = packet.obj as ImageGenerationToolDelta;
    state.generatedImageCount += delta.images?.length ?? 0;
  }

  if (packet.obj.type === PacketType.MESSAGE_END) {
    state.isComplete = true;
  }

  handleCitationPacket(state, packet);
  handleDocumentPacket(state, packet);
  handleStreamingStatusPacket(state, packet);
  handleStopPacket(state, packet);
  handleToolAfterMessagePacket(state, packet);
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

  const prevProcessedIndex = state.nextPacketIndex;

  for (let i = state.nextPacketIndex; i < rawPackets.length; i++) {
    const packet = rawPackets[i];
    if (packet) {
      processPacket(state, packet);
    }
  }

  state.nextPacketIndex = rawPackets.length;

  // Only rebuild result arrays when new packets arrived — preserves array identity so memoized
  // consumers can bail out.
  if (prevProcessedIndex !== rawPackets.length) {
    state.toolGroups = buildGroupsFromKeys(state, state.toolGroupKeys);
    state.potentialDisplayGroups = buildGroupsFromKeys(
      state,
      state.displayGroupKeys,
    );
  }

  return state;
}

// Map group keys -> GroupedPacket (spread packets to force a new array reference for change
// detection), filter to groups with meaningful content, sort by turn then tab.
function buildGroupsFromKeys(
  state: ProcessedMessageState,
  keys: Set<string>,
): GroupedPacket[] {
  return Array.from(keys)
    .map((key) => {
      const { turn_index, tab_index } = parseToolKey(key);
      const packets = state.groupedPacketsMap.get(key);
      return packets ? { turn_index, tab_index, packets: [...packets] } : null;
    })
    .filter(
      (g): g is GroupedPacket => g !== null && hasContentPackets(g.packets),
    )
    .sort((a, b) => {
      if (a.turn_index !== b.turn_index) {
        return a.turn_index - b.turn_index;
      }
      return a.tab_index - b.tab_index;
    });
}
