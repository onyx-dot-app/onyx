import { render, screen } from "@tests/setup/test-utils";
import {
  Packet,
  PacketType,
  StopReason,
} from "@/app/app/services/streamingModels";
import type { MinimalAgent } from "@/lib/agents/types";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import {
  AgentTimeline,
  MAX_HOISTED_STEPS,
} from "@/lib/timeline/chat/AgentTimeline";
import type {
  TransformedStep,
  TurnGroup,
} from "@/lib/timeline/chat/transformers";

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

function step(tabIndex: number): TransformedStep {
  const packets: Packet[] = [
    {
      placement: { turn_index: 0, tab_index: tabIndex },
      obj: { type: PacketType.SEARCH_TOOL_START, is_internet_search: true },
    },
  ];
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

// Parallel calls render as one step each, in order.
const parallelTurn: TurnGroup[] = [
  { turnIndex: 0, steps: [step(0)] },
  { turnIndex: 0, steps: [step(1)] },
];
const noTurns: TurnGroup[] = [];
const sequentialTurn: TurnGroup[] = [{ turnIndex: 0, steps: [step(0)] }];

beforeEach(() => {
  useChatSessionStore.setState({ sessions: new Map(), currentSessionId: "s" });
  useChatSessionStore.getState().createSession("s");
});

const command: Packet[] = [
  {
    placement: { turn_index: MAX_HOISTED_STEPS, tab_index: 0 },
    obj: {
      type: PacketType.EXEC_COMMAND_START,
      cmd: "npm test",
      workdir: null,
    },
  },
];
// More steps than a hoisted run has, so they collapse into one run card.
const longRun: TurnGroup[] = [
  ...Array.from({ length: MAX_HOISTED_STEPS }, (_, index) => ({
    turnIndex: index,
    steps: [step(index)],
  })),
  {
    turnIndex: MAX_HOISTED_STEPS,
    steps: [
      {
        key: "command",
        groupKey: "command",
        turnIndex: MAX_HOISTED_STEPS,
        tabIndex: 0,
        packets: command,
        nestedCalls: [],
        streamPackets: command,
        codeMode: null,
      },
    ],
  },
];

describe("AgentTimeline's collapsed run card", () => {
  it("titles a working run by its current step", () => {
    render(<AgentTimeline turnGroups={longRun} chatState={{ agent }} />);

    expect(screen.getByText("Running npm...")).toBeVisible();
  });

  it("says how long a finished run worked", () => {
    render(
      <AgentTimeline
        turnGroups={longRun}
        chatState={{ agent }}
        stopPacketSeen
        processingDurationSeconds={12}
      />
    );

    expect(screen.getByText(/^Worked for 12/)).toBeVisible();
  });

  it("titles a stopped run as a finished one", () => {
    render(
      <AgentTimeline
        turnGroups={longRun}
        chatState={{ agent }}
        stopPacketSeen
        stopReason={StopReason.USER_CANCELLED}
        processingDurationSeconds={12}
      />
    );

    expect(screen.getByText(/^Worked for 12/)).toBeVisible();
    expect(screen.queryByText(/stopped/i)).not.toBeInTheDocument();
  });

  it("does not time a later run by the response's start", () => {
    render(
      <AgentTimeline
        turnGroups={longRun}
        chatState={{ agent }}
        stopPacketSeen
        processingDurationSeconds={12}
        isFirstRun={false}
      />
    );

    expect(screen.getByText("Worked")).toBeVisible();
  });

  it("times a later run from its first step", async () => {
    let now = 1_000_000;
    const clock = jest.spyOn(Date, "now").mockImplementation(() => now);
    try {
      const view = render(
        <AgentTimeline
          turnGroups={longRun.slice(0, 1)}
          chatState={{ agent }}
          isFirstRun={false}
        />
      );
      now += 40_000;
      view.rerender(
        <AgentTimeline
          turnGroups={longRun}
          chatState={{ agent }}
          isFirstRun={false}
        />
      );
      view.rerender(
        <AgentTimeline
          turnGroups={longRun}
          chatState={{ agent }}
          isFirstRun={false}
          stopPacketSeen
        />
      );

      expect(await screen.findByText(/^Worked for 40/)).toBeVisible();
    } finally {
      clock.mockRestore();
    }
  });
});

describe("AgentTimeline while a tool call waits for the user", () => {
  it.each([
    ["parallel tool calls", parallelTurn, false, "approval"],
    ["a preamble", sequentialTurn, true, "approval"],
    ["a preamble and a question", sequentialTurn, true, "answer"],
    ["a preamble and only a question", noTurns, true, "answer"],
  ] as const)(
    "names the wait after %s",
    (_, turnGroups, hasDisplayContent, awaitingUser) => {
      render(
        <AgentTimeline
          turnGroups={turnGroups}
          chatState={{ agent }}
          hasDisplayContent={hasDisplayContent}
          awaitingUser={awaitingUser}
        />
      );

      expect(
        screen.getByText(
          awaitingUser === "approval"
            ? "Waiting for your approval..."
            : "Waiting for your answer..."
        )
      ).toBeVisible();
    }
  );
});
