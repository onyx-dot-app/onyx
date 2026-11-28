import { act, render, screen } from "@tests/setup/test-utils";
import userEvent from "@testing-library/user-event";
import type { MinimalAgent } from "@/lib/agents/types";
import type { Message } from "@/app/app/types";
import { PacketType, StopReason } from "@/app/app/services/streamingModels";
import type { ChatSubagent } from "@/lib/chat/types";
import { SubagentBar, SubagentView } from "@/sections/chat/SubagentView";

const FILE_ID = "3f2a9c1e-0000-4000-8000-000000000000";

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

const placement = { turn_index: 0, tab_index: 0 };
const answer: Message = {
  nodeId: 2,
  messageId: 2,
  parentNodeId: 1,
  type: "assistant",
  message: "",
  files: [],
  toolCall: null,
  packets: [
    {
      placement,
      obj: {
        type: PacketType.MESSAGE_START,
        id: "answer",
        content: "",
        final_documents: null,
      },
    },
    {
      placement,
      obj: {
        type: PacketType.MESSAGE_DELTA,
        content: `See [the report](/api/chat/file/${FILE_ID}).`,
      },
    },
    {
      placement,
      obj: { type: PacketType.STOP, stop_reason: StopReason.FINISHED },
    },
  ],
};

jest.mock("@/providers/VoiceModeProvider", () => ({
  useVoiceMode: () => ({
    resetTTS: jest.fn(),
    streamTTS: jest.fn(),
    stopTTS: jest.fn(),
    revealedCharCount: 0,
    autoPlayback: false,
    isAudioSyncActive: false,
    activeMessageNodeId: null,
    isAwaitingAutoPlaybackStart: false,
  }),
}));
// The page's query, as the app router reads it
jest.mock("next/navigation", () => ({
  ...jest.requireActual<typeof import("@tests/setup/mocks/nextNavigation")>(
    "@tests/setup/mocks/nextNavigation"
  ).nextNavigationMock,
  useSearchParams: () => new URLSearchParams(window.location.search),
}));
jest.mock("@/lib/agents/hooks", () => ({ useActiveAgent: () => agent }));
const worker: ChatSubagent = {
  id: "agent-1",
  path: "/root/worker",
  status: "complete",
  stopped_by_user: false,
  started_at: null,
  latest_run_id: 2,
  stream_id: null,
  activity_tool: null,
  model: "GPT-5",
  duration_seconds: 113,
};
let listed: ChatSubagent[] = [worker];
let refreshFailed = false;
const stopAgent = jest.fn();

jest.mock("@/lib/chat/hooks", () => ({
  ...jest.requireActual("@/lib/chat/hooks"),
  useChatSubagents: () => ({ agents: listed, loaded: true, stopAgent }),
  useSubagentTranscript: () => ({
    messages: [answer],
    loading: false,
    failed: refreshFailed,
  }),
}));

function shownSubagent(): string | null {
  return new URLSearchParams(window.location.search).get("subagent");
}

beforeEach(() => {
  listed = [worker];
  refreshFailed = false;
  window.history.replaceState(null, "", "/app?chatId=chat-1&subagent=agent-1");
});

test("the view shows the parent divider over the transcript, and the divider opens the parent", () => {
  render(
    <SubagentView
      sessionId="chat-1"
      agentId="agent-1"
      parentTitle="Plan the launch"
      setPresentingDocument={jest.fn()}
    />
  );

  const divider = screen.getByRole("button", { name: "Open parent chat" });
  expect(divider).toHaveTextContent("Subagent of · Plan the launch");
  expect(screen.getByRole("button", { name: "the report" })).toBeVisible();

  act(() => divider.click());
  expect(shownSubagent()).toBeNull();
  expect(new URLSearchParams(window.location.search).get("chatId")).toBe(
    "chat-1"
  );
});

test("a failed refresh keeps the transcript it has", () => {
  refreshFailed = true;
  render(
    <SubagentView
      sessionId="chat-1"
      agentId="agent-1"
      parentTitle={null}
      setPresentingDocument={jest.fn()}
    />
  );

  expect(screen.getByRole("button", { name: "the report" })).toBeVisible();
  expect(
    screen.queryByText("Could not load this agent's conversation.")
  ).toBeNull();
});

test("the bar shows the model and how long the agent took, and Open parent goes back", () => {
  render(<SubagentBar sessionId="chat-1" agentId="agent-1" />);

  expect(screen.getByText("GPT-5")).toBeVisible();
  expect(screen.getByText("Completed in 1m 53s")).toBeVisible();
  expect(screen.getByText("Runs on its own")).toBeVisible();
  expect(screen.getByRole("status")).toHaveTextContent(
    "GPT-5 subagent: Completed"
  );
  // A finished agent has no Stop
  expect(screen.queryByRole("button", { name: "Stop worker" })).toBeNull();

  act(() => screen.getByRole("button", { name: "Open parent" }).click());
  expect(shownSubagent()).toBeNull();
});

test("the bar of a running agent shows its time and its Stop", () => {
  listed = [
    {
      ...worker,
      status: "running",
      started_at: new Date(Date.now() - 12_000).toISOString(),
      duration_seconds: null,
    },
  ];
  render(<SubagentBar sessionId="chat-1" agentId="agent-1" />);

  expect(screen.getByText(/^Running \d+s$/)).toBeVisible();
  act(() => screen.getByRole("button", { name: "Stop worker" }).click());
  expect(stopAgent).toHaveBeenCalledWith("agent-1");
});

test("an agent the list does not hold shows only Open parent", () => {
  listed = [];
  render(<SubagentBar sessionId="chat-1" agentId="agent-1" />);

  expect(screen.queryByText("Runs on its own")).toBeNull();
  expect(screen.getByRole("button", { name: "Open parent" })).toBeVisible();
});

test("a cited file in a transcript opens the page's preview", async () => {
  const setPresentingDocument = jest.fn();
  render(
    <SubagentView
      sessionId="chat-1"
      agentId="agent-1"
      parentTitle={null}
      setPresentingDocument={setPresentingDocument}
    />
  );

  await userEvent.click(screen.getByRole("button", { name: "the report" }));

  expect(setPresentingDocument).toHaveBeenCalledWith({
    document_id: FILE_ID,
    semantic_identifier: "the report",
  });
});
