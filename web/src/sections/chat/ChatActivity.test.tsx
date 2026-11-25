import { act, render, screen } from "@tests/setup/test-utils";
import ChatActivity from "@/sections/chat/ChatActivity";
import { PacketType, type Packet } from "@/app/app/services/streamingModels";
import type { Message } from "@/app/app/types";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { useToolRequestUi } from "@/lib/chat/toolApprovals";
import type { ChatSessionStatus, ChatSubagent } from "@/lib/chat/types";
import { RIGHT_PANEL_FILES_TAB } from "@/lib/chat/rightPanel";
import { AppWorkspaceElementsContext } from "@/layouts/chromes/AppWorkspace";

const STATUS: ChatSessionStatus = {
  is_processing: false,
  current_stream: null,
  has_active_subagents: false,
  has_startable_input: false,
  latest_response_id: null,
  approvals_version: "",
};

function agent(path: string, status: ChatSubagent["status"]): ChatSubagent {
  return { id: path, path, status, stopped_by_user: false };
}

function serve(agents: ChatSubagent[], status = STATUS) {
  jest.spyOn(global, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    const body = url.endsWith("/agents") ? agents : status;
    return new Response(JSON.stringify(body), { status: 200 });
  });
}

function approval(tool: string, agentName: string | null): Packet {
  return {
    placement: { turn_index: 1, tab_index: 0 },
    obj: {
      type: PacketType.TOOL_APPROVAL_REQUEST,
      approval_id: tool,
      tool_call_id: `call-${tool}`,
      tool_name: tool,
      display_name: tool,
      arguments: {},
      agent_name: agentName,
    },
  };
}

function showReply(packets: Packet[]) {
  const messages: Message[] = [
    {
      nodeId: 1,
      type: "user",
      message: "Question",
      files: [],
      packets: [],
      toolCall: null,
      parentNodeId: null,
      latestChildNodeId: 2,
      childrenNodeIds: [2],
    },
    {
      nodeId: 2,
      type: "assistant",
      message: "",
      files: [],
      packets,
      toolCall: null,
      parentNodeId: 1,
      latestChildNodeId: null,
      childrenNodeIds: [],
    },
  ];
  useChatSessionStore
    .getState()
    .updateSessionMessageTree(
      "s",
      new Map(messages.map((message) => [message.nodeId, message]))
    );
}

beforeEach(() => {
  useToolRequestUi.setState({
    localStatuses: new Map(),
    localAnswers: new Map(),
    nudge: null,
  });
  useChatSessionStore.setState({ sessions: new Map(), currentSessionId: "s" });
  useChatSessionStore.getState().createSession("s");
});

afterEach(() => jest.restoreAllMocks());

// The app chrome's slot, where the card pins
function renderActivity() {
  return render(
    <AppWorkspaceElementsContext.Provider
      value={{
        workspace: { current: null },
        page: { current: null },
        panelToggleSlot: null,
        activitySlot: document.body,
      }}
    >
      <ChatActivity sessionId="s" />
    </AppWorkspaceElementsContext.Provider>
  );
}

test("shows nothing for a chat without requests, agents or files", async () => {
  serve([]);
  const view = renderActivity();
  await act(async () => undefined);
  expect(view.container).toBeEmptyDOMElement();
});

test("a waiting approval leads the trigger and its row scrolls to the card", async () => {
  serve([]);
  showReply([approval("run_command", "researcher")]);
  renderActivity();

  act(() => screen.getByRole("button", { name: "Activity" }).click());
  expect(screen.getByText("Needs You")).toBeVisible();
  expect(screen.getByText("researcher")).toBeVisible();
  act(() => screen.getByText("Approve run_command").click());

  expect(useToolRequestUi.getState().nudge?.requestId).toBe("run_command");
  // The card stays open until the user closes it
  expect(screen.getByText("Needs You")).toBeVisible();
  act(() => screen.getByRole("button", { name: "Activity" }).click());
  expect(screen.queryByText("Needs You")).toBeNull();
});

test("a request this client already decided leaves the card at once", async () => {
  serve([]);
  showReply([approval("run_command", null), approval("send_email", null)]);
  useToolRequestUi.setState({
    localStatuses: new Map([["run_command", "approved"]]),
  });
  renderActivity();

  act(() => screen.getByRole("button", { name: "Activity" }).click());
  expect(screen.getByText("Approve send_email")).toBeVisible();
  expect(screen.queryByText("Approve run_command")).toBeNull();
});

test("an agent that a streaming reply starts shows while the reply streams", async () => {
  jest.useFakeTimers();
  try {
    let agents: ChatSubagent[] = [];
    let status = STATUS;
    jest.spyOn(global, "fetch").mockImplementation(async (input) => {
      const body = String(input).endsWith("/agents") ? agents : status;
      return new Response(JSON.stringify(body), { status: 200 });
    });
    useChatSessionStore.getState().updateChatState("s", "streaming");
    renderActivity();
    await act(async () => jest.advanceTimersByTimeAsync(0));
    expect(screen.queryByRole("button", { name: "Activity" })).toBeNull();

    agents = [agent("/root/poet", "running")];
    status = { ...STATUS, has_active_subagents: true };
    await act(async () => jest.advanceTimersByTimeAsync(5000));
    act(() => screen.getByRole("button", { name: "Activity" }).click());
    expect(screen.getByText("poet")).toBeVisible();
  } finally {
    jest.useRealTimers();
  }
});

test("lists running agents on one line each and folds the finished ones", async () => {
  serve(
    [
      agent("/root/poet", "running"),
      agent("/root/researcher", "complete"),
      { ...agent("/root/sleeper", "cancelled"), stopped_by_user: true },
    ],
    { ...STATUS, has_active_subagents: true }
  );
  renderActivity();

  const trigger = await screen.findByRole("button", { name: "Activity" });
  act(() => trigger.click());
  expect(screen.getByText("poet")).toBeVisible();
  expect(screen.getByText("Running")).toBeVisible();
  expect(screen.queryByText("researcher")).toBeNull();

  const finished = screen.getByRole("button", { name: /Previous agents/ });
  expect(finished).toHaveTextContent("2");
  expect(finished).toHaveAttribute("aria-expanded", "false");
  act(() => finished.click());
  expect(screen.getByText("researcher")).toBeVisible();
  expect(screen.getByText("Done")).toBeVisible();
  expect(screen.getByText("Stopped")).toBeVisible();
});

test("View all files shows the Files list even while a file is open", async () => {
  serve([]);
  const file = {
    file_id: "file-1",
    name: "main.py",
    title: null,
    path: "/w/main.py",
    display_path: "/w/main.py",
    size: 10,
    mime_type: "text/x-python",
    artifact_id: "artifact-1",
    version: 1,
    thumbnail_file_id: null,
  };
  showReply([
    {
      placement: { turn_index: 0, tab_index: 0 },
      obj: { type: PacketType.PUBLISH_FILES_END, files: [file], error: null },
    },
  ]);
  const store = useChatSessionStore.getState();
  store.updateCurrentRightPanel({ type: "openFile", file, pinned: false });
  store.updateCurrentRightPanel({ type: "closePanel" });
  renderActivity();

  act(() => screen.getByRole("button", { name: "Activity" }).click());
  act(() => screen.getByText("View 1 file").click());

  const panel = useChatSessionStore.getState().sessions.get("s")?.rightPanel;
  expect(panel?.mode).not.toBe("closed");
  expect(panel?.activeId).toBe(RIGHT_PANEL_FILES_TAB);
});
