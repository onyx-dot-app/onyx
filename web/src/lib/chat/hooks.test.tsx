import { renderHook } from "@testing-library/react";
import {
  Packet,
  PacketType,
  ToolApprovalRequest,
} from "@/app/app/services/streamingModels";
import { useToolApprovals } from "@/lib/chat/hooks";
import { useToolApprovalUi } from "@/lib/chat/toolApprovals";

function request(
  approvalId: string,
  turnIndex: number,
  agentName: string | null = null
): Packet {
  return {
    placement: { turn_index: turnIndex, tab_index: 0 },
    obj: {
      type: PacketType.TOOL_APPROVAL_REQUEST,
      approval_id: approvalId,
      tool_call_id: `call-${approvalId}`,
      tool_name: "mcp__3__github__create_issue",
      display_name: "Create issue",
      arguments: { title: "Bug" },
      agent_name: agentName,
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
  it("keeps records of decided requests and leaves waiting ones out", () => {
    const first = request("first", 1);
    const packets = [first, request("second", 2), resolved("first", 1)];

    const { result } = renderHook(() => useToolApprovals(packets));

    expect(result.current).toEqual({
      records: [
        { turnIndex: 1, request: requestObj(first), status: "approved" },
      ],
      awaitingApproval: true,
    });
  });

  it("follows packets appended to the same array", () => {
    const packets: Packet[] = [request("first", 1)];
    const { result, rerender } = renderHook(() => useToolApprovals(packets));
    expect(result.current.records).toEqual([]);

    // Streams append to the array they already passed.
    packets.push(resolved("first", 1));
    rerender();

    expect(result.current.records[0]?.status).toBe("approved");
    expect(result.current.awaitingApproval).toBe(false);
  });

  it("does not wait on a background agent's request", () => {
    const packets = [request("agent", 1, "Researcher")];

    const { result } = renderHook(() => useToolApprovals(packets));

    expect(result.current).toEqual({ records: [], awaitingApproval: false });
  });
});
