import { render, screen } from "@tests/setup/test-utils";
import { Packet, PacketType } from "@/app/app/services/streamingModels";
import type { MinimalAgent } from "@/lib/agents/types";
import { ParallelTimelineTabs } from "@/app/app/message/messageComponents/timeline/ParallelTimelineTabs";
import type { TransformedStep } from "@/app/app/message/messageComponents/timeline/transformers";

const agent: MinimalAgent = {
  id: 0,
  name: "Default Chat",
  description: "",
  tools: [],
  starter_messages: null,
  document_sets: [],
  is_public: true,
  is_listed: true,
  display_priority: null,
  is_featured: false,
  builtin_persona: true,
  owner: null,
  owner_group: null,
  user_permission: "VIEWER",
};

function step(tabIndex: number, packets: Packet[]): TransformedStep {
  return {
    key: `0-${tabIndex}`,
    groupKey: `0-${tabIndex}`,
    turnIndex: 0,
    tabIndex,
    packets,
    nestedCalls: [],
    streamPackets: packets,
    codeMode: null,
  };
}

// The stream order: debug, tool start, arguments, then the approval packets.
const placement = { turn_index: 0, tab_index: 0 };
const approvalStep = step(0, [
  {
    placement,
    obj: {
      type: PacketType.TOOL_CALL_DEBUG,
      tool_call_id: "call",
      tool_name: "mcp__3__github__create_issue",
      tool_args: {},
    },
  },
  {
    placement,
    obj: {
      type: PacketType.CUSTOM_TOOL_START,
      tool_name: "mcp__3__github__create_issue",
      display_name: "Create issue",
    },
  },
  {
    placement,
    obj: {
      type: PacketType.CUSTOM_TOOL_ARGS,
      tool_name: "mcp__3__github__create_issue",
      tool_args: { title: "Bug" },
    },
  },
  {
    placement,
    obj: {
      type: PacketType.TOOL_APPROVAL_REQUEST,
      approval_id: "approval",
      tool_call_id: "call",
      tool_name: "mcp__3__github__create_issue",
      display_name: "Create issue",
      arguments: { title: "Bug" },
      expires_at: "2099-01-01T00:00:00Z",
    },
  },
  {
    placement,
    obj: {
      type: PacketType.TOOL_APPROVAL_RESOLVED,
      approval_id: "approval",
      outcome: "approved",
    },
  },
]);
const searchStep = step(1, [
  {
    placement: { turn_index: 0, tab_index: 1 },
    obj: { type: PacketType.SEARCH_TOOL_START, is_internet_search: true },
  },
]);

describe("ParallelTimelineTabs", () => {
  it("names the tab after the first activity packet, not the debug packet", () => {
    render(
      <ParallelTimelineTabs
        turnGroup={{
          turnIndex: 0,
          isParallel: true,
          steps: [approvalStep, searchStep],
        }}
        chatState={{ agent }}
        stopPacketSeen={false}
        isLastTurnGroup
        isFirstTurnGroup
      />
    );

    expect(screen.getByRole("tab", { name: /^Create issue/ })).toBeVisible();
    expect(screen.getByRole("tab", { name: /^Web Search/ })).toBeVisible();
  });
});
