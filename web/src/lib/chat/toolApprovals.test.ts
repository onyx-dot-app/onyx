import {
  Packet,
  PacketType,
  StopReason,
  ToolApprovalResolved,
} from "@/app/app/services/streamingModels";
import type { ApprovalDecisionResponse } from "@/lib/chat/types";
import {
  AGENT_WATCH_GRACE_READS,
  type AgentWatch,
  decidedStatus,
  nextAgentWatch,
  orderApprovalsByTurn,
  readToolApprovals,
  type ToolApproval,
  toolApprovalStatus,
  useToolApprovalUi,
} from "@/lib/chat/toolApprovals";
import type { ApprovalStatus } from "@/lib/approvals/types";
import type { GroupedPacket } from "@/app/app/message/messageComponents/timeline/hooks/packetProcessor";

function request(approvalId: string, agentName: string | null = null): Packet {
  return {
    placement: { turn_index: 1, tab_index: 0 },
    obj: {
      type: PacketType.TOOL_APPROVAL_REQUEST,
      approval_id: approvalId,
      tool_call_id: `call-${approvalId}`,
      tool_name: "mcp__3__github__create_issue",
      display_name: "Create issue",
      arguments: {},
      agent_name: agentName,
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

function stopPacket(stopReason?: StopReason): Packet {
  return {
    placement: { turn_index: 9, tab_index: 0 },
    obj: { type: PacketType.STOP, stop_reason: stopReason },
  };
}

/** Each request's status in one response, with these local statuses. */
function statuses(
  packets: Packet[],
  local = new Map<string, ApprovalStatus>()
) {
  return readToolApprovals(packets).entries.map((entry) =>
    toolApprovalStatus(entry, local.get(entry.request.approval_id))
  );
}

beforeEach(() =>
  useToolApprovalUi.setState({
    localStatuses: new Map(),
    nudge: null,
    agentWatch: null,
  })
);

describe("readToolApprovals", () => {
  it("keeps the same read while appended packets cannot change it", () => {
    const packets = [request("a")];
    const first = readToolApprovals(packets);

    packets.push({
      placement: { turn_index: 2, tab_index: 0 },
      obj: { type: PacketType.MESSAGE_DELTA, content: "text" },
    });
    expect(readToolApprovals(packets)).toBe(first);

    packets.push(resolved("a", "approved"));
    expect(readToolApprovals(packets).entries[0]?.outcome).toBe("approved");
  });
});

describe("toolApprovalStatus", () => {
  it.each([
    ["approved", "approved"],
    ["approved_for_chat", "approvedForSession"],
    ["rejected", "rejected"],
    ["disabled", "disabled"],
    ["cancelled", "closed"],
  ] as const)("shows the %s outcome as %s", (outcome, status) => {
    expect(statuses([request("a"), resolved("a", outcome)])).toEqual([status]);
  });

  it("uses a local decision until the resolution arrives, then the resolution", () => {
    const local = new Map([["a", "approved" as const]]);
    expect(statuses([request("a")], local)).toEqual(["approved"]);
    expect(statuses([request("a"), resolved("a", "rejected")], local)).toEqual([
      "rejected",
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

  it.each([
    ["a server stop for another reason", StopReason.FINISHED, null],
    ["a server stop for another reason", StopReason.FINISHED, "Researcher"],
    ["the approval wait's stop", StopReason.AWAITING_APPROVAL, null],
    ["a stop this client added", undefined, null],
  ])(
    "keeps a request pending after %s (agent %s) until its outcome arrives",
    (_, stopReason, agent) => {
      const packets = [request("a", agent), stopPacket(stopReason)];
      expect(statuses(packets)).toEqual(["pending"]);
      expect(statuses([...packets, resolved("a", "cancelled")])).toEqual([
        "closed",
      ]);
    }
  );

  it("keeps a local decision after a stop until the outcome arrives", () => {
    const local = new Map([["a", "rejected" as const]]);
    expect(
      statuses([request("a"), stopPacket(StopReason.FINISHED)], local)
    ).toEqual(["rejected"]);
  });
});

describe("nextAgentWatch", () => {
  const start: AgentWatch = { sessionId: "s", reads: 0, sawRunning: false };
  const read = (watch: AgentWatch | null, running: boolean) =>
    watch && nextAgentWatch(watch, { has_active_subagents: running });

  it("waits for the resumed agent, then ends once it settles", () => {
    let watch: AgentWatch | null = start;
    // The decision returns before the agent host starts.
    watch = read(watch, false);
    watch = read(watch, false);
    watch = read(watch, true);
    watch = read(watch, true);
    expect(watch).toEqual({ sessionId: "s", reads: 4, sawRunning: true });
    expect(read(watch, false)).toBeNull();
  });

  it("ends after the grace reads when the agent never runs", () => {
    let watch: AgentWatch | null = start;
    for (let index = 1; index < AGENT_WATCH_GRACE_READS; index++) {
      watch = read(watch, false);
      expect(watch?.reads).toBe(index);
    }
    expect(read(watch, false)).toBeNull();
  });

  it("applies a status read only to the watched chat", () => {
    useToolApprovalUi.getState().watchAgents("s");
    useToolApprovalUi
      .getState()
      .noteAgentStatus("other", { has_active_subagents: true });
    expect(useToolApprovalUi.getState().agentWatch).toEqual(start);
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
      continuation: null,
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
