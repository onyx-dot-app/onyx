import { beforeEach, describe, expect, it } from "@jest/globals";

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
  readToolApprovals,
  toolApprovalStatus,
  useToolApprovalUi,
} from "@/chat/toolApprovals";
import { orderCardsByTurn } from "@/chat/toolCards";

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

function statusOf(packets: Packet[], local?: "approved") {
  return toolApprovalStatus(readToolApprovals(packets)[0]!, local);
}

describe("toolApprovalStatus", () => {
  beforeEach(() => {
    useToolApprovalUi.setState({ localStatuses: new Map(), nudgeSeq: 0 });
  });

  it("waits until something resolves the request", () => {
    expect(statusOf([request("a")])).toBe("pending");
  });

  it.each([
    ["approved", "approved"],
    ["approved_for_chat", "approvedForSession"],
    ["rejected", "rejected"],
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

  // A subagent's request outlives the root's stop; the server resolves the root's own requests.
  it.each<[string, Packet]>([
    [
      "ends the response",
      {
        placement: { turn_index: 0 },
        obj: { type: PacketType.STOP, stop_reason: StopReason.FINISHED },
      },
    ],
    [
      "waits for approval",
      {
        placement: { turn_index: 0 },
        obj: {
          type: PacketType.STOP,
          stop_reason: StopReason.AWAITING_USER,
        },
      },
    ],
    [
      "has no reason",
      { placement: { turn_index: 0 }, obj: { type: PacketType.STOP } },
    ],
  ])("keeps a request open after a stop that %s", (_, pause) => {
    expect(statusOf([request("a"), pause])).toBe("pending");
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
      continuation: null,
    };
    expect(decidedStatus(response)).toBe(status);
  });
});

describe("orderCardsByTurn", () => {
  it("places each card after the display groups of its own and earlier turns", () => {
    const approval = (turnIndex: number) => ({
      turnIndex,
      request: request(`t${turnIndex}`).obj as ToolApprovalRequest,
      status: "pending" as const,
    });
    const order = orderCardsByTurn(
      [{ turn_index: 0 }, { turn_index: 2 }],
      [approval(2), approval(1)],
    ).map((entry) =>
      entry.kind === "display"
        ? `text${entry.group.turn_index}`
        : `card${entry.card.turnIndex}`,
    );
    expect(order).toEqual(["text0", "card1", "text2", "card2"]);
  });
});
