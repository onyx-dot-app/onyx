/**
 * Test helpers for MultiToolRenderer component testing
 * Provides factory functions to create test data with sensible defaults
 */

import { render } from "@tests/setup/test-utils";
import { PacketType, Packet } from "@/app/chat/services/streamingModels";
import MultiToolRenderer from "@/app/chat/message/messageComponents/MultiToolRenderer";

/**
 * Create a tool packet with sensible defaults
 */
export const createToolPacket = (
  turn_index: number,
  type: "search" | "custom" | "reasoning" | "fetch" = "custom"
): Packet => {
  const packetTypes = {
    search: PacketType.SEARCH_TOOL_START,
    custom: PacketType.CUSTOM_TOOL_START,
    reasoning: PacketType.REASONING_START,
    fetch: PacketType.FETCH_TOOL_START,
  };

  return {
    turn_index,
    obj: {
      type: packetTypes[type],
      tool_name: `Tool ${turn_index + 1}`,
      tool_id: `tool_${turn_index}`,
    },
  } as Packet;
};

/**
 * Create a packet group representing a single internal search tool
 * with both queries and at least one result document.
 *
 * This is used to exercise the two-step internal search rendering
 * in MultiToolRenderer and SearchToolRendererV2.
 */
export const createInternalSearchToolGroup = (
  turn_index: number = 0
): { turn_index: number; packets: Packet[] } => {
  const packets: Packet[] = [
    {
      turn_index,
      obj: {
        type: PacketType.SEARCH_TOOL_START,
        is_internet_search: false,
      } as any,
    },
    {
      turn_index,
      obj: {
        type: PacketType.SEARCH_TOOL_QUERIES_DELTA,
        queries: ["example query"],
      } as any,
    },
    {
      turn_index,
      obj: {
        type: PacketType.SEARCH_TOOL_DOCUMENTS_DELTA,
        documents: [
          {
            document_id: "doc-1",
            semantic_identifier: "Doc 1",
          },
        ],
      } as any,
    },
    {
      turn_index,
      obj: {
        type: PacketType.SECTION_END,
      } as any,
    },
  ];

  return { turn_index, packets };
};

/**
 * Create an array of tool groups
 */
export const createToolGroups = (count: number) =>
  Array.from({ length: count }, (_, i) => ({
    turn_index: i,
    packets: [createToolPacket(i)],
  }));

/**
 * Create minimal mock chatState
 */
export const createMockChatState = (overrides = {}) => ({
  assistant: {
    id: 1,
    name: "Test Assistant",
    description: "Test assistant for testing",
    tools: [],
    starter_messages: null,
    document_sets: [],
    is_public: true,
    is_visible: true,
    display_priority: null,
    is_default_persona: false,
    builtin_persona: false,
    owner: null,
  },
  handleFeedbackChange: jest.fn().mockResolvedValue(undefined),
  ...overrides,
});

/**
 * Render MultiToolRenderer with sensible defaults
 * Makes tests extremely concise and readable
 */
export const renderMultiToolRenderer = (
  config: {
    toolCount?: number;
    isComplete?: boolean;
    isFinalAnswerComing?: boolean;
    stopPacketSeen?: boolean;
    onAllToolsDisplayed?: () => void;
    chatState?: any;
    packetGroups?: { turn_index: number; packets: Packet[] }[];
  } = {}
) => {
  const {
    toolCount = 3,
    isComplete = false,
    isFinalAnswerComing = false,
    stopPacketSeen = false,
    onAllToolsDisplayed,
    chatState,
    packetGroups,
  } = config;

  return render(
    <MultiToolRenderer
      packetGroups={packetGroups || createToolGroups(toolCount)}
      chatState={chatState || createMockChatState()}
      isComplete={isComplete}
      isFinalAnswerComing={isFinalAnswerComing}
      stopPacketSeen={stopPacketSeen}
      onAllToolsDisplayed={onAllToolsDisplayed}
    />
  );
};
