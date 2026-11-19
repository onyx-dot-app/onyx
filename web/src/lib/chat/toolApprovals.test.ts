import {
  Packet,
  PacketType,
  StopReason,
  ToolApprovalResolved,
} from "@/app/app/services/streamingModels";
import type { ApprovalDecisionResponse } from "@/lib/chat/types";
import type { Message } from "@/app/app/types";
import {
  asksUser,
  decidedStatus,
  readToolApprovals,
  readToolQuestions,
  readWaitingToolRequests,
  toolApprovalStatus,
  toolQuestionStatus,
  useToolRequestUi,
} from "@/lib/chat/toolApprovals";
import type { ApprovalStatus } from "@/lib/approvals/types";

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

function question(questionRequestId: string, turnIndex = 1): Packet {
  return {
    placement: { turn_index: turnIndex, tab_index: 0 },
    obj: {
      type: PacketType.TOOL_QUESTION_REQUEST,
      question_request_id: questionRequestId,
      tool_call_id: `call-${questionRequestId}`,
      questions: [
        {
          id: "scope",
          header: "Scope",
          question: "Which files?",
          options: [
            { label: "All (Recommended)", description: "Every file." },
            { label: "Docs", description: "Only the docs." },
          ],
        },
      ],
    },
  };
}

function answered(questionRequestId: string): Packet {
  return {
    placement: { turn_index: 1, tab_index: 0 },
    obj: {
      type: PacketType.TOOL_QUESTION_RESOLVED,
      question_request_id: questionRequestId,
      outcome: "answered",
      answered_via: "card",
      answers: [
        { question_id: "scope", option_label: "Docs", user_note: "and tests" },
      ],
      message: null,
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
  useToolRequestUi.setState({
    localStatuses: new Map(),
    localAnswers: new Map(),
    nudge: null,
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

  it("reads a resolution that the replay and the live stream both send once", () => {
    const packets = [request("a"), resolved("a", "approved")];
    const replayed = readToolApprovals(packets).entries;

    packets.push(resolved("a", "approved"));
    expect(readToolApprovals(packets).entries).toEqual(replayed);
    expect(replayed).toHaveLength(1);
  });
});

describe("readToolQuestions", () => {
  it("keeps the same read until a question packet arrives", () => {
    const packets = [question("q")];
    const first = readToolQuestions(packets);

    packets.push(request("a"), stopPacket(StopReason.AWAITING_USER));
    expect(readToolQuestions(packets)).toBe(first);
    expect(first.entries[0]?.resolution).toBeNull();

    packets.push(answered("q"));
    expect(readToolQuestions(packets).entries[0]?.resolution).toMatchObject({
      outcome: "answered",
    });
  });
});

describe("toolQuestionStatus", () => {
  it("uses a local answer until the resolution arrives, then the resolution", () => {
    const local = { kind: "closed" } as const;
    const [waiting] = readToolQuestions([question("q")]).entries;
    expect(toolQuestionStatus(waiting!, undefined)).toEqual({
      kind: "pending",
    });
    expect(toolQuestionStatus(waiting!, local)).toBe(local);

    const [ended] = readToolQuestions([question("q"), answered("q")]).entries;
    expect(toolQuestionStatus(ended!, local)).toEqual({
      kind: "answered",
      answers: [
        { question_id: "scope", option_label: "Docs", user_note: "and tests" },
      ],
      message: null,
    });
  });

  it("shows a question that its run stopped as cancelled", () => {
    const [ended] = readToolQuestions([
      question("q"),
      {
        placement: { turn_index: 1, tab_index: 0 },
        obj: {
          type: PacketType.TOOL_QUESTION_RESOLVED,
          question_request_id: "q",
          outcome: "cancelled",
        },
      },
    ]).entries;
    expect(toolQuestionStatus(ended!, undefined)).toEqual({
      kind: "cancelled",
    });
  });
});

describe("asksUser", () => {
  it("finds approval requests and questions", () => {
    expect(asksUser([stopPacket()])).toBe(false);
    expect(asksUser([request("a")])).toBe(true);
    expect(asksUser([question("q")])).toBe(true);
  });
});

describe("readWaitingToolRequests", () => {
  function message(
    nodeId: number,
    type: Message["type"],
    packets: Packet[],
    parentNodeId: number | null
  ): Message {
    return {
      nodeId,
      messageId: nodeId,
      type,
      message: "",
      files: [],
      packets,
      toolCall: null,
      parentNodeId,
      latestChildNodeId: nodeId + 1,
      childrenNodeIds: [nodeId + 1],
    };
  }

  it("lists both kinds, oldest response first and by turn", () => {
    const tree = new Map(
      [
        message(1, "user", [], null),
        message(2, "assistant", [question("old", 3), answered("old")], 1),
        message(3, "user", [], 2),
        message(
          4,
          "assistant",
          [question("later", 4), request("first"), answered("other")],
          3
        ),
      ].map((item) => [item.nodeId, item])
    );

    expect(
      readWaitingToolRequests(tree).map((item) =>
        item.kind === "approval"
          ? item.request.approval_id
          : item.request.question_request_id
      )
    ).toEqual(["first", "later"]);
  });
});

describe("forgetStatuses", () => {
  it("drops local approval statuses and question answers by request ID", () => {
    const ui = useToolRequestUi.getState();
    ui.recordStatus("a", "approved");
    ui.recordAnswer("q", { kind: "closed" });
    ui.recordAnswer("other", { kind: "closed" });

    useToolRequestUi.getState().forgetStatuses(["a", "q"]);

    const state = useToolRequestUi.getState();
    expect([...state.localStatuses.keys()]).toEqual([]);
    expect([...state.localAnswers.keys()]).toEqual(["other"]);
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
    ["the approval wait's stop", StopReason.AWAITING_USER, null],
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

describe("nudgeRequest", () => {
  afterEach(() => jest.useRealTimers());

  it("drops a nudge that no card handled", () => {
    jest.useFakeTimers();
    useToolRequestUi.getState().nudgeRequest("a");
    expect(useToolRequestUi.getState().nudge?.requestId).toBe("a");

    jest.advanceTimersByTime(2000);

    expect(useToolRequestUi.getState().nudge).toBeNull();
  });
});
