import {
  Packet,
  PacketType,
  ToolApprovalResolved,
} from "@/app/app/services/streamingModels";
import type { Message } from "@/app/app/types";
import type { MessageTreeState } from "@/app/app/services/messageTree";
import type { ApprovalDecisionResponse } from "@/lib/chat/types";
import {
  decidedStatus,
  findPendingToolApprovalId,
  orderApprovalsByTurn,
  readToolApprovals,
  type ToolApproval,
  toolApprovalStatus,
  useToolApprovalUi,
} from "@/lib/chat/toolApprovals";
import type { ApprovalStatus } from "@/lib/approvals/types";
import type { GroupedPacket } from "@/app/app/message/messageComponents/timeline/hooks/packetProcessor";

function request(
  approvalId: string,
  toolName = "mcp__3__github__create_issue",
  expiresAt = "2099-01-01T00:00:00Z"
): Packet {
  return {
    placement: { turn_index: 1, tab_index: 0 },
    obj: {
      type: PacketType.TOOL_APPROVAL_REQUEST,
      approval_id: approvalId,
      tool_call_id: `call-${approvalId}`,
      tool_name: toolName,
      display_name: "Create issue",
      arguments: {},
      expires_at: expiresAt,
    },
  };
}

function resolved(
  approvalId: string,
  outcome: ToolApprovalResolved["outcome"]
): Packet {
  return {
    placement: { turn_index: 1, tab_index: 0 },
    obj: {
      type: PacketType.TOOL_APPROVAL_RESOLVED,
      approval_id: approvalId,
      outcome,
    },
  };
}

const stop: Packet = {
  placement: { turn_index: 9, tab_index: 0 },
  obj: { type: PacketType.STOP },
};

/** A user question and one response per packet list, as a multi-model turn. */
function chat(...responses: Packet[][]): MessageTreeState {
  const responseIds = responses.map((_, index) => index + 2);
  const question: Message = {
    nodeId: 1,
    type: "user",
    message: "Question",
    files: [],
    packets: [],
    toolCall: null,
    parentNodeId: null,
    latestChildNodeId: responseIds[0],
    childrenNodeIds: responseIds,
  };
  return new Map<number, Message>([
    [1, question],
    ...responses.map((packets, index): [number, Message] => [
      index + 2,
      {
        nodeId: index + 2,
        type: "assistant",
        message: "",
        files: [],
        packets,
        toolCall: null,
        parentNodeId: 1,
      },
    ]),
  ]);
}

/** Each request's status in one response, with these local statuses. */
function statuses(
  packets: Packet[],
  local = new Map<string, ApprovalStatus>()
) {
  const { entries, stopped } = readToolApprovals(packets);
  return entries.map((entry) =>
    toolApprovalStatus(entry, local.get(entry.request.approval_id), stopped)
  );
}

beforeEach(() =>
  useToolApprovalUi.setState({ localStatuses: new Map(), nudge: null })
);

describe("toolApprovalStatus", () => {
  it.each([
    ["approved", "approved"],
    ["approved_for_chat", "approvedForSession"],
    ["rejected", "rejected"],
    ["expired", "expired"],
    ["disabled", "disabled"],
    ["cancelled", "closed"],
  ] as const)("shows the %s outcome as %s", (outcome, status) => {
    expect(statuses([request("a"), resolved("a", outcome)])).toEqual([status]);
  });

  it("keeps a request pending past its deadline until the server resolves it", () => {
    expect(statuses([request("a", undefined, "2020-01-01T00:00:00Z")])).toEqual(
      ["pending"]
    );
  });

  it("uses a local decision until the resolution arrives, then the resolution", () => {
    const local = new Map([["a", "approved" as const]]);
    expect(statuses([request("a")], local)).toEqual(["approved"]);
    expect(statuses([request("a"), resolved("a", "expired")], local)).toEqual([
      "expired",
    ]);
  });

  it("ignores a resolution without a known outcome", () => {
    const unknown = {
      placement: { turn_index: 1, tab_index: 0 },
      obj: {
        type: PacketType.TOOL_APPROVAL_RESOLVED,
        approval_id: "a",
        outcome: "deferred",
      },
    } as unknown as Packet;
    const local = new Map<string, ApprovalStatus>([["a", "approved"]]);

    expect(statuses([request("a"), unknown], local)).toEqual(["approved"]);
    expect(statuses([request("a"), unknown])).toEqual(["pending"]);
  });

  it("closes an unresolved request once the response stops", () => {
    expect(statuses([request("a"), stop])).toEqual(["closed"]);
  });
});

describe("findPendingToolApprovalId", () => {
  it("finds a waiting request in any response of the latest turn", () => {
    expect(
      findPendingToolApprovalId(
        chat([request("done"), resolved("done", "approved")], [request("b")])
      )
    ).toBe("b");
  });

  it.each([
    ["resolved", [request("a"), resolved("a", "rejected")]],
    ["stopped", [request("a"), stop]],
  ])("ignores a %s request", (_, packets) => {
    expect(findPendingToolApprovalId(chat(packets))).toBeNull();
  });

  it("ignores a request this client decided before its resolution arrived", () => {
    useToolApprovalUi.setState({ localStatuses: new Map([["a", "approved"]]) });
    expect(findPendingToolApprovalId(chat([request("a")]))).toBeNull();
  });
});

describe("decidedStatus", () => {
  it.each([
    ["APPROVED", "USER", "approved"],
    ["APPROVED", "SESSION_GRANT", "approvedForSession"],
    ["REJECTED", "USER", "rejected"],
    ["REJECTED", "POLICY", "disabled"],
  ] as const)("shows %s via %s as %s", (decision, decidedVia, status) => {
    const response: ApprovalDecisionResponse = {
      approval_id: "a",
      decision,
      decided_via: decidedVia,
    };
    expect(decidedStatus(response)).toBe(status);
  });
});

describe("nudgeApproval", () => {
  afterEach(() => jest.useRealTimers());

  it("drops a nudge that no card handled", () => {
    jest.useFakeTimers();
    useToolApprovalUi.getState().nudgeApproval("a");
    expect(useToolApprovalUi.getState().nudge?.approvalId).toBe("a");

    jest.advanceTimersByTime(2000);

    expect(useToolApprovalUi.getState().nudge).toBeNull();
  });
});

describe("orderApprovalsByTurn", () => {
  function displayGroup(turnIndex: number): GroupedPacket {
    return {
      turn_index: turnIndex,
      tab_index: 0,
      packets: [],
      nestedCalls: [],
      streamPackets: [],
      codeMode: null,
    };
  }
  function approval(approvalId: string, turnIndex: number): ToolApproval {
    const { obj } = request(approvalId);
    if (obj.type !== PacketType.TOOL_APPROVAL_REQUEST)
      throw new Error("not a request");
    return { turnIndex, request: obj, status: "pending" };
  }

  it("places each card after the text of its own and earlier turns", () => {
    const entries = orderApprovalsByTurn(
      [displayGroup(0), displayGroup(2), displayGroup(5)],
      [approval("first", 2), approval("second", 2), approval("third", 3)]
    );

    expect(
      entries.map((entry) =>
        entry.kind === "display"
          ? `text-${entry.turnIndex}`
          : entry.approval.request.approval_id
      )
    ).toEqual(["text-0", "text-2", "first", "second", "third", "text-5"]);
  });

  it("places cards before any text when the model wrote none yet", () => {
    const entries = orderApprovalsByTurn([displayGroup(4)], [approval("a", 1)]);

    expect(entries.map((entry) => entry.kind)).toEqual(["approval", "display"]);
  });
});
