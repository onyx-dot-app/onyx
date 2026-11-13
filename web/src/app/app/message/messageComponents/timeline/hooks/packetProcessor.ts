import {
  Packet,
  PacketType,
  StreamingCitation,
  StopReason,
  CitationInfo,
  SearchToolDocumentsDelta,
  FetchToolDocuments,
  Stop,
  GeneratedImage,
  MessageStart,
  ToolCallArgumentDelta,
  isCodeInterpreterToolType,
} from "@/app/app/services/streamingModels";
import { CitationMap } from "@/app/app/types";
import { OnyxDocument } from "@/lib/search/types";
import {
  isActualToolCallPacket,
  isToolPacket,
  isDisplayPacket,
} from "@/app/app/services/packetUtils";
import {
  getToolKey,
  parseToolKey,
} from "@/app/app/message/messageComponents/toolDisplayHelpers";
import {
  CodeModeProgram,
  isCodeModePacket,
  isGroupEndPacket,
  isNestedPacket,
  NestedCall,
  nestedCallSnapshot,
  nextCodeModeProgram,
} from "@/app/app/message/messageComponents/timeline/packetHelpers";

// Re-export parseToolKey for consumers that import from this module
export { parseToolKey };

// ============================================================================
// Types
// ============================================================================

export interface PlacedImage extends GeneratedImage {
  turnIndex: number;
}

export interface ProcessorState {
  nodeId: number;
  nextPacketIndex: number;
  // Packets through the latest accepted user message
  acceptedPacketCount: number;

  // Citations
  citations: StreamingCitation[];
  seenCitationDocIds: Set<string>;
  citationMap: CitationMap;

  // Documents
  documentMap: Map<string, OnyxDocument>;

  // Packet grouping
  groupedPacketsMap: Map<string, Packet[]>;
  // Nested calls of each group by sub_turn_index, placed at parent level once
  // per packet
  nestedCallsMap: Map<string, Map<number, Packet[]>>;
  // The last nested-call list built for each group; unchanged calls keep their
  // objects across batches
  nestedCallSnapshots: Map<string, NestedCall[]>;
  seenGroupKeys: Set<string>;
  groupKeysWithSectionEnd: Set<string>;
  // Groups whose tool has started: a tool packet other than a streamed
  // argument arrived
  startedToolGroupKeys: Set<string>;
  // The program of each code mode group, updated once per packet
  codeModePrograms: Map<string, CodeModeProgram>;

  // Pre-categorized groups (populated during packet processing)
  toolGroupKeys: Set<string>;
  displayGroupKeys: Set<string>;

  // Images from every image generation call, nested calls included, in
  // arrival order and unique by file_id
  generatedImages: PlacedImage[];

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
  /** The group's own packets, without the packets of nested calls. Step kind,
   * renderer, header, and end read only these. */
  packets: Packet[];
  /** The tool calls nested under this group, ordered by sub_turn_index. */
  nestedCalls: NestedCall[];
  /** Every packet of the group, nested calls included, in stream order. Only
   * renderers that interleave nested sections read it (coding agent). */
  streamPackets: Packet[];
  /** The program of a code mode group; null for other groups. */
  codeMode: CodeModeProgram | null;
}

// ============================================================================
// State Creation
// ============================================================================

export function createInitialState(nodeId: number): ProcessorState {
  return {
    nodeId,
    nextPacketIndex: 0,
    acceptedPacketCount: 0,
    citations: [],
    seenCitationDocIds: new Set(),
    citationMap: {},
    documentMap: new Map(),
    groupedPacketsMap: new Map(),
    nestedCallsMap: new Map(),
    nestedCallSnapshots: new Map(),
    seenGroupKeys: new Set(),
    groupKeysWithSectionEnd: new Set(),
    startedToolGroupKeys: new Set(),
    codeModePrograms: new Map(),
    toolGroupKeys: new Set(),
    displayGroupKeys: new Set(),
    generatedImages: [],
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

function injectSectionEnd(state: ProcessorState, groupKey: string): void {
  if (state.groupKeysWithSectionEnd.has(groupKey)) {
    return; // Already has SECTION_END
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

/**
 * Content packet types that indicate a group has meaningful content to display
 */
const CONTENT_PACKET_TYPES_SET = new Set<PacketType>([
  PacketType.USER_MESSAGE,
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
      return isCodeInterpreterToolType(
        (packet.obj as ToolCallArgumentDelta).tool_type
      );
    }
    return CONTENT_PACKET_TYPES_SET.has(type);
  });
}

/**
 * Packet types that indicate final answer content is coming
 */
const FINAL_ANSWER_PACKET_TYPES_SET = new Set<PacketType>([
  PacketType.MESSAGE_START,
  PacketType.MESSAGE_DELTA,
]);

// ============================================================================
// Packet Handlers
// ============================================================================

function handleTurnTransition(state: ProcessorState, packet: Packet): void {
  const currentTurnIndex = packet.placement.turn_index;

  // Get all previous turn indices from seen group keys
  const previousTurnIndices = new Set(
    Array.from(state.seenGroupKeys).map((key) => parseToolKey(key).turn_index)
  );

  const isNewTurnIndex = !previousTurnIndices.has(currentTurnIndex);

  // If we see a new turn_index (not just tab_index), inject SECTION_END for previous groups
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

  // Add to citation map immediately for rendering
  state.citationMap[citationInfo.citation_number] = citationInfo.document_id;

  // Also add to citations array for CitedSourcesToggle (deduplicated)
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

function handleImagePacket(state: ProcessorState, packet: Packet): void {
  if (packet.obj.type !== PacketType.IMAGE_GENERATION_TOOL_DELTA) {
    return;
  }
  const delta = packet.obj;
  const seenFileIds = new Set(state.generatedImages.map((i) => i.file_id));
  const newImages: PlacedImage[] = [];
  for (const image of delta.images) {
    if (seenFileIds.has(image.file_id)) continue;
    seenFileIds.add(image.file_id);
    newImages.push({ ...image, turnIndex: packet.placement.turn_index });
  }
  if (newImages.length > 0) {
    // A new array, so memoized consumers see the change
    state.generatedImages = [...state.generatedImages, ...newImages];
  }
}

function handleStreamingStatusPacket(
  state: ProcessorState,
  packet: Packet
): void {
  if (isNestedPacket(packet)) return;

  if (FINAL_ANSWER_PACKET_TYPES_SET.has(packet.obj.type as PacketType)) {
    state.finalAnswerComing = true;
  }

  // Capture pre-answer processing time from MESSAGE_START packet
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

  // Extract and store the stop reason
  const stopPacket = packet.obj as Stop;
  state.stopReason = stopPacket.stop_reason;

  // Inject SECTION_END for all group keys that don't have one
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
    })
  );
}

function handleToolAfterMessagePacket(
  state: ProcessorState,
  packet: Packet,
  groupKey: string
): void {
  // The model can write a message and then call a tool, so the answer is not
  // final yet. Every tool packet up to the tool's start is part of a new call,
  // even when the call's arguments streamed before the message. Packets after
  // the start (such as a code mode cell's closing record) are not. Reasoning is
  // not a tool call.
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

  const subTurnIndex = packet.placement.sub_turn_index;
  if (subTurnIndex === undefined || subTurnIndex === null) return;
  const calls =
    state.nestedCallsMap.get(groupKey) ?? new Map<number, Packet[]>();
  state.nestedCallsMap.set(groupKey, calls);
  const call = calls.get(subTurnIndex) ?? [];
  // Placed at parent level, so the tool's own renderer reads it as a direct call
  call.push({
    ...packet,
    placement: { ...packet.placement, sub_turn_index: null },
  });
  calls.set(subTurnIndex, call);
}

// ============================================================================
// Main Processing Function
// ============================================================================

function processPacket(state: ProcessorState, packet: Packet): void {
  if (!packet) return;

  // Handle turn transitions (inject SECTION_END for previous groups)
  handleTurnTransition(state, packet);

  // Track group key
  const groupKey = getToolKey(
    packet.placement.turn_index,
    packet.placement.tab_index
  );
  state.seenGroupKeys.add(groupKey);

  // Track the packets that end a group (same rule as isToolComplete)
  if (isGroupEndPacket(packet)) {
    state.groupKeysWithSectionEnd.add(groupKey);
  }

  // Add packet to group
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

  // Handle specific packet types
  handleImagePacket(state, packet);
  handleCitationPacket(state, packet);
  handleDocumentPacket(state, packet);
  handleStreamingStatusPacket(state, packet);
  handleStopPacket(state, packet);
  handleToolAfterMessagePacket(state, packet, groupKey);
}

export function processPackets(
  state: ProcessorState,
  rawPackets: Packet[]
): ProcessorState {
  // Handle reset (packets array shrunk - upstream replaced with shorter list)
  if (state.nextPacketIndex > rawPackets.length) {
    state = createInitialState(state.nodeId);
  }

  // Track if we processed any new packets
  const prevProcessedIndex = state.nextPacketIndex;

  // Process only new packets
  for (let i = state.nextPacketIndex; i < rawPackets.length; i++) {
    const packet = rawPackets[i];
    if (packet) {
      processPacket(state, packet);
      if (packet.obj.type === PacketType.USER_MESSAGE)
        state.acceptedPacketCount = i + 1;
    }
  }

  state.nextPacketIndex = rawPackets.length;

  // Only rebuild result arrays if we processed new packets
  // This prevents creating new references when nothing changed
  if (prevProcessedIndex !== rawPackets.length) {
    // Build result arrays after processing new packets
    state.toolGroups = buildGroupsFromKeys(state, state.toolGroupKeys);
    state.potentialDisplayGroups = buildGroupsFromKeys(
      state,
      state.displayGroupKeys
    );
  }

  return state;
}

/**
 * Build GroupedPacket array from a set of group keys.
 * Filters to only include groups with meaningful content and sorts by turn/tab index.
 *
 * @example
 * // Input: state.groupedPacketsMap + keys Set
 * // ┌─────────────────────────────────────────────────────┐
 * // │ groupedPacketsMap = {                               │
 * // │   "0-0" → [packet1, packet2]                       │
 * // │   "0-1" → [packet3]                                │
 * // │   "1-0" → [packet4, packet5]                       │
 * // │   "2-0" → [empty_packet]  ← no content packets     │
 * // │ }                                                  │
 * // │ keys = Set{"0-0", "0-1", "1-0", "2-0"}             │
 * // └─────────────────────────────────────────────────────┘
 * //
 * // Step 1: Map keys → GroupedPacket (parse key, split parent packets from nested calls)
 * // ┌─────────────────────────────────────────────────────┐
 * // │ "0-0" → { turn_index:0, tab_index:0, packets:[...] }│
 * // │ "0-1" → { turn_index:0, tab_index:1, packets:[...] }│
 * // │ "1-0" → { turn_index:1, tab_index:0, packets:[...] }│
 * // │ "2-0" → { turn_index:2, tab_index:0, packets:[...] }│
 * // └─────────────────────────────────────────────────────┘
 * //
 * // Step 2: Filter (hasContentPackets check)
 * // ┌─────────────────────────────────────────────────────┐
 * // │ ✓ "0-0" has MESSAGE_START        → keep            │
 * // │ ✓ "0-1" has SEARCH_TOOL_START    → keep            │
 * // │ ✓ "1-0" has PYTHON_TOOL_START    → keep            │
 * // │ ✗ "2-0" no content packets       → filtered out    │
 * // └─────────────────────────────────────────────────────┘
 * //
 * // Step 3: Sort by turn_index, then tab_index
 * // ┌─────────────────────────────────────────────────────┐
 * // │ Output: GroupedPacket[]                             │
 * // ├─────────────────────────────────────────────────────┤
 * // │ [0] turn_index=0, tab_index=0, packets=[...]       │
 * // │ [1] turn_index=0, tab_index=1, packets=[...]       │
 * // │ [2] turn_index=1, tab_index=0, packets=[...]       │
 * // └─────────────────────────────────────────────────────┘
 */
function buildGroupsFromKeys(
  state: ProcessorState,
  keys: Set<string>
): GroupedPacket[] {
  return Array.from(keys)
    .map((key) => {
      const { turn_index, tab_index } = parseToolKey(key);
      const streamPackets = state.groupedPacketsMap.get(key);
      if (!streamPackets) return null;
      const nestedCalls = nestedCallSnapshot(
        state.nestedCallsMap.get(key) ?? new Map<number, Packet[]>(),
        state.nestedCallSnapshots.get(key)
      );
      state.nestedCallSnapshots.set(key, nestedCalls);
      // New array references let React detect changes for re-renders
      return {
        turn_index,
        tab_index,
        packets: streamPackets.filter((p) => !isNestedPacket(p)),
        nestedCalls,
        streamPackets: [...streamPackets],
        codeMode: state.codeModePrograms.get(key) ?? null,
      };
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
