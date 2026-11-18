import { act, render, screen, within } from "@tests/setup/test-utils";
import ToolApprovalsRegion from "@/sections/chat/ToolApprovalsRegion";
import {
  Packet,
  PacketType,
  StopReason,
  type ToolApprovalResolved,
} from "@/app/app/services/streamingModels";
import type { Message } from "@/app/app/types";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { useToolRequestUi } from "@/lib/chat/toolApprovals";

function request(tool: string, agentName: string | null = null): Packet {
  return {
    placement: { turn_index: 1, tab_index: 0 },
    obj: {
      type: PacketType.TOOL_APPROVAL_REQUEST,
      approval_id: tool,
      tool_call_id: `call-${tool}`,
      tool_name: tool,
      display_name: tool,
      arguments: {},
      agent_name: agentName,
    },
  };
}

function resolved(
  tool: string,
  outcome: ToolApprovalResolved["outcome"] = "approved"
): Packet {
  return {
    placement: { turn_index: 1, tab_index: 0 },
    obj: {
      type: PacketType.TOOL_APPROVAL_RESOLVED,
      approval_id: tool,
      outcome,
    },
  };
}

const serverStop: Packet = {
  placement: { turn_index: 2, tab_index: 0 },
  obj: { type: PacketType.STOP, stop_reason: StopReason.FINISHED },
};

function question(
  nodeId: number,
  parentNodeId: number | null,
  children: number[]
): Message {
  return {
    nodeId,
    type: "user",
    message: "Question",
    files: [],
    packets: [],
    toolCall: null,
    parentNodeId,
    latestChildNodeId: children[0],
    childrenNodeIds: children,
  };
}

function answer(
  nodeId: number,
  parentNodeId: number,
  packets: Packet[],
  extra: Partial<Message> = {}
): Message {
  return {
    nodeId,
    type: "assistant",
    message: "",
    files: [],
    packets,
    toolCall: null,
    parentNodeId,
    latestChildNodeId: nodeId + 1,
    childrenNodeIds: [nodeId + 1],
    ...extra,
  };
}

function showChat(messages: Message[]) {
  useChatSessionStore
    .getState()
    .updateSessionMessageTree(
      "s",
      new Map(messages.map((message) => [message.nodeId, message]))
    );
}

/** The tools of the waiting cards, in the order the region shows them. */
function waitingTools(): string[] {
  return screen
    .getAllByRole("button", { name: /^Approval requested: / })
    .map((button) =>
      (button.textContent ?? "").replace(/^Approval requested: /, "")
    );
}

beforeEach(() => {
  useToolRequestUi.setState({
    localStatuses: new Map(),
    localAnswers: new Map(),
    nudge: null,
  });
  useChatSessionStore.setState({ sessions: new Map(), currentSessionId: "s" });
  useChatSessionStore.getState().createSession("s");
});

test("shows every waiting card of the branch, oldest response first", () => {
  showChat([
    question(1, null, [2]),
    // The reply ended: the server resolved its own requests and its agent
    // still waits. A request without an outcome still waits after the stop.
    answer(2, 1, [
      request("agent_tool", "Researcher"),
      request("decided_tool"),
      resolved("decided_tool"),
      request("cancelled_tool"),
      resolved("cancelled_tool", "cancelled"),
      request("unresolved_tool"),
      serverStop,
    ]),
    question(3, 2, [4]),
    answer(4, 3, [request("first_tool"), request("second_tool")]),
  ]);

  render(<ToolApprovalsRegion modelProviderLookup={new Map()} />);

  expect(waitingTools()).toEqual([
    "agent_tool",
    "unresolved_tool",
    "first_tool",
    "second_tool",
  ]);
  expect(screen.getByText("Researcher wants to run agent_tool")).toBeVisible();
});

test("names the model of each answer in a multi-model turn", () => {
  showChat([
    question(1, null, [2, 3]),
    answer(2, 1, [request("left_tool")], { modelDisplayName: "Model A" }),
    answer(3, 1, [request("right_tool")], { modelDisplayName: "Model B" }),
  ]);

  render(<ToolApprovalsRegion modelProviderLookup={new Map()} />);

  const cards = screen.getAllByTestId("tool-approval-card");
  expect(cards).toHaveLength(2);
  expect(within(cards[0]!).getByText("Model A")).toBeVisible();
  expect(within(cards[1]!).getByText("Model B")).toBeVisible();
});

test("a decided card shows its record in place until the resolution arrives", () => {
  const packets = [request("create_issue")];
  showChat([question(1, null, [2]), answer(2, 1, packets)]);
  render(<ToolApprovalsRegion modelProviderLookup={new Map()} />);

  act(() =>
    useToolRequestUi.getState().recordStatus("create_issue", "approved")
  );
  expect(
    within(screen.getByTestId("tool-approvals-region")).getByRole("status")
  ).toHaveTextContent("Approved: create_issue");

  // The reply's timeline keeps the record from here on.
  act(() =>
    showChat([
      question(1, null, [2]),
      answer(2, 1, [...packets, resolved("create_issue")]),
    ])
  );
  expect(screen.queryByTestId("tool-approvals-region")).not.toBeInTheDocument();
});
