import { act, fireEvent, render, screen } from "@tests/setup/test-utils";
import { Packet, PacketType } from "@/app/app/services/streamingModels";
import type { MinimalAgent } from "@/lib/agents/types";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { AgentTimeline } from "@/app/app/message/messageComponents/timeline/AgentTimeline";
import type {
  TransformedStep,
  TurnGroup,
} from "@/app/app/message/messageComponents/timeline/transformers";

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

const parallelTurn: TurnGroup[] = [
  { turnIndex: 0, isParallel: true, steps: [step(0), step(1)] },
];
const sequentialTurn: TurnGroup[] = [
  { turnIndex: 0, isParallel: false, steps: [step(0)] },
];

beforeEach(() => {
  jest.useFakeTimers({ now: 1_000 });
  useChatSessionStore.setState({ sessions: new Map(), currentSessionId: "s" });
  useChatSessionStore.getState().createSession("s");
  useChatSessionStore.getState().setStreamingStartTime("s", 1_000);
});

afterEach(() => jest.useRealTimers());

describe("AgentTimeline while a tool call waits for approval", () => {
  it.each([
    ["parallel tool calls", parallelTurn, false],
    ["a preamble", sequentialTurn, true],
  ])("names the wait after %s", (_, turnGroups, hasDisplayContent) => {
    render(
      <AgentTimeline
        turnGroups={turnGroups}
        chatState={{ agent }}
        hasDisplayContent={hasDisplayContent}
        awaitingApproval
      />
    );

    expect(screen.getByText("Waiting for your approval")).toBeVisible();
  });

  it("leaves the wait out of the timer after the header remounts", () => {
    const { rerender } = render(
      <AgentTimeline turnGroups={parallelTurn} chatState={{ agent }} />
    );
    const timeline = (awaitingApproval: boolean) => (
      <AgentTimeline
        turnGroups={parallelTurn}
        chatState={{ agent }}
        awaitingApproval={awaitingApproval}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "Expand timeline" }));
    act(() => jest.advanceTimersByTime(5_100));
    expect(screen.getByText("5s")).toBeVisible();

    rerender(timeline(true));
    act(() => jest.advanceTimersByTime(600_000));
    rerender(timeline(false));

    // Collapsed parallel calls show tabs, so the timer header unmounts.
    fireEvent.click(screen.getByRole("button", { name: "Collapse timeline" }));
    act(() => jest.advanceTimersByTime(2_000));
    fireEvent.click(screen.getByRole("button", { name: "Expand timeline" }));
    act(() => jest.advanceTimersByTime(100));

    expect(screen.getByText("7s")).toBeVisible();
  });
});
