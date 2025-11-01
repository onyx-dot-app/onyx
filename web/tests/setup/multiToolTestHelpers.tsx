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
  ind: number,
  type: "search" | "custom" | "reasoning" | "fetch" = "search"
): Packet => {
  const packetTypes = {
    search: PacketType.SEARCH_TOOL_START,
    custom: PacketType.CUSTOM_TOOL_START,
    reasoning: PacketType.REASONING_START,
    fetch: PacketType.FETCH_TOOL_START,
  };

  return {
    ind,
    obj: {
      type: packetTypes[type],
      tool_name: `Tool ${ind + 1}`,
      tool_id: `tool_${ind}`,
    },
  } as Packet;
};

/**
 * Create an array of tool groups
 */
export const createToolGroups = (count: number) =>
  Array.from({ length: count }, (_, i) => ({
    ind: i,
    packets: [createToolPacket(i)],
  }));

/**
 * Create minimal mock chatState
 */
export const createMockChatState = (overrides = {}) => ({
  assistant: { name: "Test Assistant", id: 1 },
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
    packetGroups?: { ind: number; packets: Packet[] }[];
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
