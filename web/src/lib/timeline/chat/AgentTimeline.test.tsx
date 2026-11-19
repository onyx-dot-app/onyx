import { render, screen } from "@tests/setup/test-utils";
import { Packet, PacketType } from "@/app/app/services/streamingModels";
import type { MinimalAgent } from "@/lib/agents/types";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { AgentTimeline } from "@/lib/timeline/chat/AgentTimeline";
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
            ? "Waiting for your approval"
            : "Waiting for your answer"
        )
      ).toBeVisible();
    }
  );
});
