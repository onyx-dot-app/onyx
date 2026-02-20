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
} from "@/app/app/services/streamingModels";
import { CitationMap } from "@/app/app/interfaces";
import { OnyxDocument } from "@/lib/search/interfaces";
import {
  isActualToolCallPacket,
  isToolPacket,
  isDisplayPacket,
} from "@/app/app/services/packetUtils";
import { parseToolKey } from "@/app/app/message/messageComponents/toolDisplayHelpers";

// Re-export parseToolKey for consumers that import from this module
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
  PacketType.MESSAGE_START,
  PacketType.SEARCH_TOOL_START,
  PacketType.IMAGE_GENERATION_TOOL_START,
  PacketType.PYTHON_TOOL_START,
  PacketType.CUSTOM_TOOL_START,
  PacketType.FILE_READER_START,
  PacketType.FETCH_TOOL_START,
  PacketType.MEMORY_TOOL_START,
  PacketType.MEMORY_TOOL_NO_ACCESS,
  PacketType.REASONING_START,
  PacketType.DEEP_RESEARCH_PLAN_START,
  PacketType.RESEARCH_AGENT_START,
]);

function hasContentPackets(packets: Packet[]): boolean {
  return packets.some((packet) =>
    CONTENT_PACKET_TYPES_SET.has(packet.obj.type as PacketType)
  );
}

/**
 * Packet types that indicate final answer content is coming
 */
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

function handleStreamingStatusPacket(
  state: ProcessorState,
  packet: Packet
): void {
  // Check if final answer is coming
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
}

function handleToolAfterMessagePacket(
  state: ProcessorState,
  packet: Packet
): void {
  // Handles case where we get a Message packet from Claude, and then tool
  // calling packets. We use isActualToolCallPacket instead of isToolPacket
  // to exclude reasoning packets - reasoning is just the model thinking,
  // not an actual tool call that would produce new content.
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

  // Handle TopLevelBranching packets - these tell us how many parallel branches to expect
  if (packet.obj.type === PacketType.TOP_LEVEL_BRANCHING) {
    handleTopLevelBranching(state, packet);
    // Don't add this packet to any group, it's just metadata
    return;
  }

  // Handle turn transitions (inject SECTION_END for previous groups)
  handleTurnTransition(state, packet);

  // Track group key
  const groupKey = getGroupKey(packet);
  state.seenGroupKeys.add(groupKey);

  // Track SECTION_END and ERROR packets (both indicate completion)
  if (
    packet.obj.type === PacketType.SECTION_END ||
    packet.obj.type === PacketType.ERROR
  ) {
    state.groupKeysWithSectionEnd.add(groupKey);
  }

  // Check if this is the first packet in the group (before adding)
  const existingGroup = state.groupedPacketsMap.get(groupKey);
  const isFirstPacket = !existingGroup;

  // Add packet to group
  addPacketToGroup(state, packet, groupKey);

  // Categorize on first packet of each group
  if (isFirstPacket) {
    if (isToolPacket(packet, false)) {
      state.toolGroupKeys.add(groupKey);
    }
    if (isDisplayPacket(packet)) {
      state.displayGroupKeys.add(groupKey);
    }

    // Track image generation for header display
    if (packet.obj.type === PacketType.IMAGE_GENERATION_TOOL_START) {
      state.isGeneratingImage = true;
    }
  }

  // Count generated images from DELTA packets
  if (packet.obj.type === PacketType.IMAGE_GENERATION_TOOL_DELTA) {
    const delta = packet.obj as ImageGenerationToolDelta;
    state.generatedImageCount += delta.images?.length ?? 0;
  }

  // Handle specific packet types
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

  // Track if we processed any new packets
  const prevProcessedIndex = state.nextPacketIndex;

  // Process only new packets
  for (let i = state.nextPacketIndex; i < rawPackets.length; i++) {
    const packet = rawPackets[i];
    if (packet) {
      processPacket(state, packet);
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
 * // Step 1: Map keys → GroupedPacket (parse key, lookup packets)
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
      const packets = state.groupedPacketsMap.get(key);
      // Spread to create new array reference - ensures React detects changes for re-renders
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
