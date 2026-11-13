// Pure incremental packet -> state reducer for one assistant message (faithful port of web's
// packetProcessor). Advances a cursor, groups packets into timeline steps by turn/tab, synthesizes
// SECTION_END so a step reads complete, and keeps the 9a citations/documents/completion tracking.

import {
  CitationMap,
  SearchDoc,
  StreamingCitation,
} from "@/chat/contracts/documents";
import {
  CitationInfo,
  CODE_INTERPRETER_TOOL_TYPES,
  FetchToolDocuments,
  GeneratedImage,
  ImageGenerationToolDelta,
  MessageStart,
  Packet,
  PacketType,
  SearchToolDocumentsDelta,
  Stop,
  StopReason,
  ToolCallArgumentDelta,
} from "@/chat/streamingModels";
import {
  isActualToolCallPacket,
  isDisplayPacket,
  isToolPacket,
} from "@/chat/timeline/packetUtils";
import {
  CodeModeProgram,
  isCodeModePacket,
  isGroupEndPacket,
  isNestedPacket,
  NestedCall,
  nestedCallSnapshot,
  nextCodeModeProgram,
} from "@/chat/timeline/packetHelpers";
import { parseToolKey } from "@/chat/timeline/toolDisplay";

export interface ProcessedMessageState {
  nodeId: number;
  nextPacketIndex: number; // cursor — process only packets past this index

  citationMap: CitationMap;
  citations: StreamingCitation[];
  seenCitationDocIds: Set<string>;

  documentMap: Map<string, SearchDoc>;

  groupedPacketsMap: Map<string, Packet[]>;
  // Nested calls of each group by sub_turn_index, placed at parent level once per packet
  nestedCallsMap: Map<string, Map<number, Packet[]>>;
  seenGroupKeys: Set<string>;
  groupKeysWithSectionEnd: Set<string>;
  // Groups whose tool has started: a tool packet other than a streamed argument arrived.
  startedToolGroupKeys: Set<string>;
  // The program of each code mode group, updated once per packet
  codeModePrograms: Map<string, CodeModeProgram>;
  toolGroupKeys: Set<string>;
  displayGroupKeys: Set<string>;

  // Images from every image generation call, nested calls included, unique by file_id
  generatedImages: GeneratedImage[];

  finalAnswerComing: boolean;
  stopPacketSeen: boolean;
  isComplete: boolean; // saw MESSAGE_END or STOP; drives CitedSources
  stopReason: StopReason | undefined;
  toolProcessingDuration: number | undefined;

  toolGroups: GroupedPacket[];
  potentialDisplayGroups: GroupedPacket[];
}

export interface GroupedPacket {
  turn_index: number;
  tab_index: number;
  // The group's own packets, without the packets of nested calls. Step kind, renderer, header,
  // and end read only these.
  packets: Packet[];
  // The tool calls nested under this group, ordered by sub_turn_index.
  nestedCalls: NestedCall[];
  // The program of a code mode group; null for other groups.
  codeMode: CodeModeProgram | null;
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
    nestedCallsMap: new Map(),
    seenGroupKeys: new Set(),
    groupKeysWithSectionEnd: new Set(),
    startedToolGroupKeys: new Set(),
    codeModePrograms: new Map(),
    toolGroupKeys: new Set(),
    displayGroupKeys: new Set(),
    generatedImages: [],
    finalAnswerComing: false,
    stopPacketSeen: false,
    isComplete: false,
    stopReason: undefined,
    toolProcessingDuration: undefined,
    toolGroups: [],
    potentialDisplayGroups: [],
  };
}

export function getGroupKey(packet: Packet): string {
  const turnIndex = packet.placement.turn_index;
  const tabIndex = packet.placement.tab_index ?? 0;
  return `${turnIndex}-${tabIndex}`;
}

// Synthetic SECTION_END so the group's renderer reads complete. Idempotent; omits sub_turn_index
// (parent-level), which research/coding completion checks require.
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
    if (isCodeModePacket(packet)) return true;
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
]);

// A new turn_index closes every prior open group (a new tab_index within a seen turn does not).
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
    upsertDocuments(state, (packet.obj as MessageStart).final_documents);
  }
}

function handleImagePacket(state: ProcessedMessageState, packet: Packet): void {
  if (packet.obj.type !== PacketType.IMAGE_GENERATION_TOOL_DELTA) return;
  const seenFileIds = new Set(state.generatedImages.map((i) => i.file_id));
  const newImages: GeneratedImage[] = [];
  for (const image of (packet.obj as ImageGenerationToolDelta).images) {
    if (seenFileIds.has(image.file_id)) continue;
    seenFileIds.add(image.file_id);
    newImages.push(image);
  }
  if (newImages.length > 0) {
    // A new array, so memoized consumers see the change
    state.generatedImages = [...state.generatedImages, ...newImages];
  }
}

function handleStreamingStatusPacket(
  state: ProcessedMessageState,
  packet: Packet,
): void {
  if (isNestedPacket(packet)) return;

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
  // Nothing follows Stop, so the latest text is the answer, even when its step also called a tool.
  if (state.displayGroupKeys.size > 0) {
    state.finalAnswerComing = true;
  }

  // Close every still-open group — this is why the final-answer group gets its SECTION_END (the
  // backend never sends one).
  state.seenGroupKeys.forEach((groupKey) => {
    if (!state.groupKeysWithSectionEnd.has(groupKey)) {
      injectSectionEnd(state, groupKey);
    }
  });

  // Nothing follows Stop, so each open nested call ends with the response.
  state.nestedCallsMap.forEach((calls) =>
    calls.forEach((call) => {
      if (!call.some(isGroupEndPacket)) {
        call.push({
          placement: call[0]!.placement,
          obj: { type: PacketType.SECTION_END },
        });
      }
    }),
  );
}

// The model can write a message and then call a tool, so the answer is not final yet. Every tool
// packet up to the tool's start is part of a new call, even when the call's arguments streamed
// before the message. Packets after the start (such as a code mode cell's closing record) are not.
// Reasoning is not a tool call.
function handleToolAfterMessagePacket(
  state: ProcessedMessageState,
  packet: Packet,
  groupKey: string,
): void {
  if (!isActualToolCallPacket(packet)) return;
  if (
    state.finalAnswerComing &&
    !state.stopPacketSeen &&
    !state.startedToolGroupKeys.has(groupKey)
  ) {
    state.finalAnswerComing = false;
  }
  if (packet.obj.type !== PacketType.TOOL_CALL_ARGUMENT_DELTA) {
    state.startedToolGroupKeys.add(groupKey);
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

  const subTurnIndex = packet.placement.sub_turn_index;
  if (subTurnIndex === undefined || subTurnIndex === null) return;
  const calls =
    state.nestedCallsMap.get(groupKey) ?? new Map<number, Packet[]>();
  state.nestedCallsMap.set(groupKey, calls);
  const call = calls.get(subTurnIndex) ?? [];
  // Placed at parent level, so the tool's own renderer reads it as a direct call.
  call.push({
    ...packet,
    placement: { ...packet.placement, sub_turn_index: null },
  });
  calls.set(subTurnIndex, call);
}

function processPacket(state: ProcessedMessageState, packet: Packet): void {
  if (!packet) return;

  // Older servers still send this; it must not become the first packet of a group.
  if (packet.obj.type === PacketType.TOP_LEVEL_BRANCHING) return;

  handleTurnTransition(state, packet);

  const groupKey = getGroupKey(packet);
  state.seenGroupKeys.add(groupKey);

  if (isGroupEndPacket(packet)) {
    state.groupKeysWithSectionEnd.add(groupKey);
  }

  addPacketToGroup(state, packet, groupKey);

  if (isCodeModePacket(packet)) {
    const program = state.codeModePrograms.get(groupKey) ?? {
      cellId: null,
      running: false,
    };
    state.codeModePrograms.set(groupKey, nextCodeModeProgram(program, packet));
  }

  // Debug and control packets can precede the first rendered packet.
  if (
    !state.toolGroupKeys.has(groupKey) &&
    !state.displayGroupKeys.has(groupKey)
  ) {
    if (isToolPacket(packet, false)) {
      state.toolGroupKeys.add(groupKey);
    }
    if (isDisplayPacket(packet)) {
      state.displayGroupKeys.add(groupKey);
    }
  }

  handleImagePacket(state, packet);

  if (packet.obj.type === PacketType.MESSAGE_END) {
    state.isComplete = true;
  }

  handleCitationPacket(state, packet);
  handleDocumentPacket(state, packet);
  handleStreamingStatusPacket(state, packet);
  handleStopPacket(state, packet);
  handleToolAfterMessagePacket(state, packet, groupKey);
}

export function processPackets(
  state: ProcessedMessageState,
  rawPackets: Packet[],
): ProcessedMessageState {
  // Array shrank (regenerate / history reload) -> rebuild so we never double-count a re-streamed turn.
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

  // Rebuild only when new packets arrived, to preserve array identity for memoized consumers.
  if (prevProcessedIndex !== rawPackets.length) {
    state.toolGroups = buildGroupsFromKeys(state, state.toolGroupKeys);
    state.potentialDisplayGroups = buildGroupsFromKeys(
      state,
      state.displayGroupKeys,
    );
  }

  return state;
}

// Keep each group's own packets in a new array ref (change detection); keep only content groups;
// sort by turn then tab.
function buildGroupsFromKeys(
  state: ProcessedMessageState,
  keys: Set<string>,
): GroupedPacket[] {
  return Array.from(keys)
    .map((key) => {
      const { turn_index, tab_index } = parseToolKey(key);
      const packets = state.groupedPacketsMap.get(key);
      if (!packets) return null;
      const nestedCalls = nestedCallSnapshot(
        state.nestedCallsMap.get(key) ?? new Map<number, Packet[]>(),
      );
      return {
        turn_index,
        tab_index,
        packets: packets.filter((packet) => !isNestedPacket(packet)),
        nestedCalls,
        codeMode: state.codeModePrograms.get(key) ?? null,
      };
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
