import { beforeEach, describe, expect, it } from "@jest/globals";

import type { Message } from "@/chat/interfaces";
import { upsertMessages } from "@/chat/messageTree";
import {
  Packet,
  PacketType,
  StopReason,
  ToolApprovalRequest,
} from "@/chat/streamingModels";
import type { ApprovalDecisionResponse } from "@/api/chat/approvals";
import {
  ApprovalStatus,
  decidedStatus,
  findPendingToolApprovalId,
  orderApprovalsByTurn,
  readToolApprovals,
  toolApprovalStatus,
  useToolApprovalUi,
} from "@/chat/toolApprovals";

function request(
  approvalId: string,
  toolName = "lookup",
  turnIndex = 0,
): Packet {
  return {
    placement: { turn_index: turnIndex },
    obj: {
      type: PacketType.TOOL_APPROVAL_REQUEST,
      approval_id: approvalId,
      tool_call_id: `call-${approvalId}`,
      tool_name: toolName,
      display_name: "Lookup",
      arguments: { query: "q" },
      // Long past: the device clock must never close a request.
      expires_at: "2000-01-01T00:00:00Z",
    },
  };
}

function resolved(approvalId: string, outcome: string): Packet {
  return {
    placement: { turn_index: 0 },
    obj: {
      type: PacketType.TOOL_APPROVAL_RESOLVED,
      approval_id: approvalId,
      outcome,
    },
  } as Packet;
}

const stop: Packet = {
  placement: { turn_index: 0 },
  obj: { type: PacketType.STOP, stop_reason: StopReason.FINISHED },
};

function statusOf(packets: Packet[], local?: "approved") {
  const { entries, stopped } = readToolApprovals(packets);
  return toolApprovalStatus(entries[0]!, local, stopped);
}

function node(
  nodeId: number,
  type: Message["type"],
  packets: Packet[],
  parentNodeId: number | null,
): Message {
  return {
    nodeId,
    messageId: nodeId,
    parentNodeId,
    type,
    message: "",
    files: [],
    packets,
  };
}

function treeOf(messages: Message[]) {
  return upsertMessages(new Map(), messages, false);
}

describe("toolApprovalStatus", () => {
  beforeEach(() => {
    useToolApprovalUi.setState({ localStatuses: new Map(), nudgeSeq: 0 });
  });

  it("waits until something resolves the request, whatever the deadline", () => {
    expect(statusOf([request("a")])).toBe("pending");
  });

  it.each([
    ["approved", "approved"],
    ["approved_for_chat", "approvedForSession"],
    ["rejected", "rejected"],
    ["expired", "expired"],
    ["disabled", "disabled"],
    ["cancelled", "closed"],
  ])("maps the server outcome %s to %s", (outcome, status) => {
    expect(statusOf([request("a"), resolved("a", outcome)])).toBe(status);
  });

  it("ignores an unknown outcome", () => {
    expect(statusOf([request("a"), resolved("a", "maybe")])).toBe("pending");
  });

  it("uses the local decision before the outcome arrives", () => {
    expect(statusOf([request("a")], "approved")).toBe("approved");
  });

  it("closes a request whose response stopped without an outcome", () => {
    expect(statusOf([request("a"), stop])).toBe("closed");
  });
});

describe("tool approval store", () => {
  beforeEach(() => {
    useToolApprovalUi.setState({ localStatuses: new Map(), nudgeSeq: 0 });
  });

  it("forgets the statuses that resolutions now report", () => {
    useToolApprovalUi.setState({
      localStatuses: new Map([
        ["a", "approved"],
        ["b", "approvedForSession"],
      ]),
    });
    useToolApprovalUi.getState().forgetStatuses(["a", "b"]);
    expect(useToolApprovalUi.getState().localStatuses.size).toBe(0);
  });

  it("finds a waiting request only in the latest turn", () => {
    const older = treeOf([
      node(1, "user", [], null),
      node(2, "assistant", [request("a")], 1),
    ]);
    expect(findPendingToolApprovalId(older)).toBe("a");

    const newer = treeOf([
      node(1, "user", [], null),
      node(2, "assistant", [request("a")], 1),
      node(3, "user", [], 2),
      node(4, "assistant", [request("b"), resolved("b", "rejected")], 3),
    ]);
    expect(findPendingToolApprovalId(newer)).toBeNull();
  });

  it("does not report a request this device already decided", () => {
    const tree = treeOf([
      node(1, "user", [], null),
      node(2, "assistant", [request("a")], 1),
    ]);
    useToolApprovalUi.setState({ localStatuses: new Map([["a", "rejected"]]) });
    expect(findPendingToolApprovalId(tree)).toBeNull();
  });
});

describe("decidedStatus", () => {
  it.each<
    [
      ApprovalDecisionResponse["decision"],
      ApprovalDecisionResponse["decided_via"],
      ApprovalStatus,
    ]
  >([
    ["APPROVED", "USER", "approved"],
    ["APPROVED", "SESSION_GRANT", "approvedForSession"],
    ["REJECTED", "USER", "rejected"],
    ["REJECTED", "POLICY", "disabled"],
  ])("shows %s via %s as %s", (decision, decidedVia, status) => {
    const response: ApprovalDecisionResponse = {
      approval_id: "a",
      decision,
      decided_via: decidedVia,
    };
    expect(decidedStatus(response)).toBe(status);
  });
});

describe("orderApprovalsByTurn", () => {
  it("places each card after the display groups of its own and earlier turns", () => {
    const approval = (turnIndex: number) => ({
      turnIndex,
      request: request(`t${turnIndex}`).obj as ToolApprovalRequest,
      status: "pending" as const,
    });
    const order = orderApprovalsByTurn(
      [{ turn_index: 0 }, { turn_index: 2 }],
      [approval(1), approval(2)],
    ).map((entry) =>
      entry.kind === "display"
        ? `text${entry.group.turn_index}`
        : `card${entry.approval.turnIndex}`,
    );
    expect(order).toEqual(["text0", "card1", "text2", "card2"]);
  });
});
