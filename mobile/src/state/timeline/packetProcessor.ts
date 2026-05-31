// packetProcessor.ts — incremental packet → grouped-step reducer for the timeline.
//
// Ported from web:
//   web/src/app/app/message/messageComponents/timeline/hooks/packetProcessor.ts
// Pure, imperative, ref-friendly. Processes ONLY new packets via a
// `nextPacketIndex` cursor (so an idle render does no work), groups packets by
// `${turn_index}-${tab_index}`, splits groups into tool-steps vs display
// (final-answer) groups, and injects synthetic SECTION_END on turn transitions
// and STOP. This is identity-agnostic: it indexes rawPackets[i] by position, so
// it tolerates mobile's new-array-per-packet store reducer (append-only indices).

import {
  Packet,
  PacketType,
  StreamingCitation,
  StopReason,
  CitationInfo,
  SearchToolDocumentsDelta,
  FetchToolDocuments,
  TopLevelBranching,
  Stop,
  ImageGenerationToolDelta,
  MessageStart,
  ToolCallArgumentDelta,
  CODE_INTERPRETER_TOOL_TYPES,
  OnyxDocument,
  CitationMap,
} from "@/lib/types";
import {
  isActualToolCallPacket,
  isToolPacket,
  isDisplayPacket,
} from "@/state/timeline/packetUtils";
import { parseToolKey } from "@/state/timeline/toolDisplayHelpers";

export { parseToolKey };

// ============================================================================
// Types
// ============================================================================

export interface ProcessorState {
  nodeId: number;
  nextPacketIndex: number;

  // Citations
  citations: StreamingCitation[];
  seenCitationDocIds: Set<string>;
  citationMap: CitationMap;

  // Documents
  documentMap: Map<string, OnyxDocument>;

  // Packet grouping
  groupedPacketsMap: Map<string, Packet[]>;
  seenGroupKeys: Set<string>;
  groupKeysWithSectionEnd: Set<string>;
  expectedBranches: Map<number, number>;

  // Pre-categorized groups (populated during packet processing)
  toolGroupKeys: Set<string>;
  displayGroupKeys: Set<string>;

  // Image generation status
  isGeneratingImage: boolean;
  generatedImageCount: number;

  // Streaming status
  finalAnswerComing: boolean;
  stopPacketSeen: boolean;
  stopReason: StopReason | undefined;

  // Tool processing duration from backend (captured when MESSAGE_START arrives)
  toolProcessingDuration: number | undefined;

  // Result arrays (built at end of processPackets)
  toolGroups: GroupedPacket[];
  potentialDisplayGroups: GroupedPacket[];
}

export interface GroupedPacket {
  turn_index: number;
  tab_index: number;
  packets: Packet[];
}

// ============================================================================
// State Creation
// ============================================================================

export function createInitialState(nodeId: number): ProcessorState {
  return {
    nodeId,
    nextPacketIndex: 0,
    citations: [],
    seenCitationDocIds: new Set(),
    citationMap: {},
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
    stopReason: undefined,
    toolProcessingDuration: undefined,
    toolGroups: [],
    potentialDisplayGroups: [],
  };
}

// ============================================================================
// Helper Functions
// ============================================================================

function getGroupKey(packet: Packet): string {
  const turnIndex = packet.placement.turn_index;
  const tabIndex = packet.placement.tab_index ?? 0;
  return `${turnIndex}-${tabIndex}`;
}

function injectSectionEnd(state: ProcessorState, groupKey: string): void {
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

const FINAL_ANSWER_PACKET_TYPES_SET = new Set<PacketType>([
  PacketType.MESSAGE_START,
  PacketType.MESSAGE_DELTA,
  PacketType.IMAGE_GENERATION_TOOL_START,
  PacketType.IMAGE_GENERATION_TOOL_DELTA,
]);

// ============================================================================
// Packet Handlers
// ============================================================================

function handleTopLevelBranching(state: ProcessorState, packet: Packet): void {
  const branchingPacket = packet.obj as TopLevelBranching;
  state.expectedBranches.set(
    packet.placement.turn_index,
    branchingPacket.num_parallel_branches
  );
}

function handleTurnTransition(state: ProcessorState, packet: Packet): void {
  const currentTurnIndex = packet.placement.turn_index;

  const previousTurnIndices = new Set(
    Array.from(state.seenGroupKeys).map((key) => parseToolKey(key).turn_index)
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

function handleCitationPacket(state: ProcessorState, packet: Packet): void {
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

function handleDocumentPacket(state: ProcessorState, packet: Packet): void {
  if (packet.obj.type === PacketType.SEARCH_TOOL_DOCUMENTS_DELTA) {
    const docDelta = packet.obj as SearchToolDocumentsDelta;
    if (docDelta.documents) {
      for (const doc of docDelta.documents) {
        if (doc.document_id) {
          state.documentMap.set(doc.document_id, doc);
        }
      }
    }
  } else if (packet.obj.type === PacketType.FETCH_TOOL_DOCUMENTS) {
    const fetchDocuments = packet.obj as FetchToolDocuments;
    if (fetchDocuments.documents) {
      for (const doc of fetchDocuments.documents) {
        if (doc.document_id) {
          state.documentMap.set(doc.document_id, doc);
        }
      }
    }
  }
}

function handleStreamingStatusPacket(
  state: ProcessorState,
  packet: Packet
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

function handleStopPacket(state: ProcessorState, packet: Packet): void {
  if (packet.obj.type !== PacketType.STOP || state.stopPacketSeen) {
    return;
  }

  state.stopPacketSeen = true;

  const stopPacket = packet.obj as Stop;
  state.stopReason = stopPacket.stop_reason;

  state.seenGroupKeys.forEach((groupKey) => {
    if (!state.groupKeysWithSectionEnd.has(groupKey)) {
      injectSectionEnd(state, groupKey);
    }
  });
}

function handleToolAfterMessagePacket(
  state: ProcessorState,
  packet: Packet
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
  state: ProcessorState,
  packet: Packet,
  groupKey: string
): void {
  const existingGroup = state.groupedPacketsMap.get(groupKey);
  if (existingGroup) {
    existingGroup.push(packet);
  } else {
    state.groupedPacketsMap.set(groupKey, [packet]);
  }
}

// ============================================================================
// Main Processing Function
// ============================================================================

function processPacket(state: ProcessorState, packet: Packet): void {
  if (!packet) return;

  if (packet.obj.type === PacketType.TOP_LEVEL_BRANCHING) {
    handleTopLevelBranching(state, packet);
    return;
  }

  handleTurnTransition(state, packet);

  const groupKey = getGroupKey(packet);
  state.seenGroupKeys.add(groupKey);

  if (
    packet.obj.type === PacketType.SECTION_END ||
    packet.obj.type === PacketType.ERROR
  ) {
    state.groupKeysWithSectionEnd.add(groupKey);
  }

  const existingGroup = state.groupedPacketsMap.get(groupKey);
  const isFirstPacket = !existingGroup;

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

  handleCitationPacket(state, packet);
  handleDocumentPacket(state, packet);
  handleStreamingStatusPacket(state, packet);
  handleStopPacket(state, packet);
  handleToolAfterMessagePacket(state, packet);
}

export function processPackets(
  state: ProcessorState,
  rawPackets: Packet[]
): ProcessorState {
  // Handle reset (packets array shrunk - upstream replaced with shorter list)
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

  if (prevProcessedIndex !== rawPackets.length) {
    state.toolGroups = buildGroupsFromKeys(state, state.toolGroupKeys);
    state.potentialDisplayGroups = buildGroupsFromKeys(
      state,
      state.displayGroupKeys
    );
  }

  return state;
}

/**
 * Build a GroupedPacket array from group keys: keep only groups with meaningful
 * content, sort by turn then tab. Packets are spread into a NEW array so React
 * detects change in downstream consumers.
 */
function buildGroupsFromKeys(
  state: ProcessorState,
  keys: Set<string>
): GroupedPacket[] {
  return Array.from(keys)
    .map((key) => {
      const { turn_index, tab_index } = parseToolKey(key);
      const packets = state.groupedPacketsMap.get(key);
      return packets ? { turn_index, tab_index, packets: [...packets] } : null;
    })
    .filter(
      (g): g is GroupedPacket => g !== null && hasContentPackets(g.packets)
    )
    .sort((a, b) => {
      if (a.turn_index !== b.turn_index) {
        return a.turn_index - b.turn_index;
      }
      return a.tab_index - b.tab_index;
    });
}
