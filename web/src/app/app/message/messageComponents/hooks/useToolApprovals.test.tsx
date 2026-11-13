import { renderHook } from "@testing-library/react";
import {
  Packet,
  PacketType,
  ToolApprovalRequest,
} from "@/app/app/services/streamingModels";
import {
  orderApprovalsByTurn,
  useToolApprovals,
} from "@/app/app/message/messageComponents/hooks/useToolApprovals";
import { type ToolApproval, useToolApprovalUi } from "@/lib/chat/toolApprovals";
import type { GroupedPacket } from "@/app/app/message/messageComponents/timeline/hooks/packetProcessor";

function request(approvalId: string, turnIndex: number): Packet {
  return {
    placement: { turn_index: turnIndex, tab_index: 0 },
    obj: {
      type: PacketType.TOOL_APPROVAL_REQUEST,
      approval_id: approvalId,
      tool_call_id: `call-${approvalId}`,
      tool_name: "mcp__3__github__create_issue",
      display_name: "Create issue",
      arguments: { title: "Bug" },
      expires_at: "2099-01-01T00:00:00Z",
    },
  };
}

function resolved(approvalId: string, turnIndex: number): Packet {
  return {
    placement: { turn_index: turnIndex, tab_index: 0 },
    obj: {
      type: PacketType.TOOL_APPROVAL_RESOLVED,
      approval_id: approvalId,
      outcome: "approved",
    },
  };
}

function requestObj(packet: Packet): ToolApprovalRequest {
  if (packet.obj.type !== PacketType.TOOL_APPROVAL_REQUEST) {
    throw new Error("not a request");
  }
  return packet.obj;
}

beforeEach(() =>
  useToolApprovalUi.setState({ localStatuses: new Map(), nudge: null })
);

describe("useToolApprovals", () => {
  it("gives each request of the response its status", () => {
    const first = request("first", 1);
    const second = request("second", 2);
    const packets = [first, second, resolved("first", 1)];

    const { result } = renderHook(() => useToolApprovals(packets));

    expect(result.current).toEqual([
      { turnIndex: 1, request: requestObj(first), status: "approved" },
      { turnIndex: 2, request: requestObj(second), status: "pending" },
    ]);
  });

  it("follows packets appended to the same array", () => {
    const packets: Packet[] = [request("first", 1)];
    const { result, rerender } = renderHook(() => useToolApprovals(packets));
    expect(result.current[0]?.status).toBe("pending");

    // Streams append to the array they already passed.
    packets.push(resolved("first", 1));
    rerender();

    expect(result.current[0]?.status).toBe("approved");
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
    return {
      turnIndex,
      request: requestObj(request(approvalId, turnIndex)),
      status: "pending",
    };
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
