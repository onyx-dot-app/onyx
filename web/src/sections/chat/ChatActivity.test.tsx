import { act, render, screen, waitFor } from "@tests/setup/test-utils";
import { unstable_serialize } from "swr";
import ChatActivity from "@/sections/chat/ChatActivity";
import { useChatSubagents } from "@/lib/chat/hooks";
import { PacketType, type Packet } from "@/app/app/services/streamingModels";
import type { Message } from "@/app/app/types";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { useToolRequestUi } from "@/lib/chat/toolApprovals";
import type { ChatSessionStatus, ChatSubagent } from "@/lib/chat/types";
import { RIGHT_PANEL_FILES_TAB } from "@/lib/chat/rightPanel";
import { AppWorkspaceElementsContext } from "@/layouts/chromes/AppWorkspace";
import { SubagentLinksContext } from "@/lib/chat/subagents";

const STATUS: ChatSessionStatus = {
  is_processing: false,
  current_stream: null,
  has_active_subagents: false,
  has_startable_input: false,
  latest_response_id: null,
  approvals_version: "",
};

function agent(path: string, status: ChatSubagent["status"]): ChatSubagent {
  return {
    id: path,
    path,
    status,
    stopped_by_user: false,
    started_at: null,
    stream_id: null,
    latest_run_id: null,
    activity_tool: null,
    model: null,
    duration_seconds: null,
  };
}

function shownSubagent(): string | null {
  return new URLSearchParams(window.location.search).get("subagent");
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
  window.history.replaceState(null, "", "/app?chatId=s");
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
function renderActivity(showFiles?: boolean) {
  return render(
    <AppWorkspaceElementsContext.Provider
      value={{
        workspace: { current: null },
        page: { current: null },
        panelToggleSlot: null,
        activitySlot: document.body,
      }}
    >
      <ChatActivity sessionId="s" showFiles={showFiles} />
    </AppWorkspaceElementsContext.Provider>
  );
}

const PUBLISHED_FILE = {
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

test("an agent that a streaming reply starts opens the card once per run of agents", async () => {
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
    expect(screen.getByText("poet")).toBeVisible();

    // Closed while the agents run, the card stays closed
    act(() => screen.getByRole("button", { name: "Activity" }).click());
    agents = [agent("/root/poet", "running"), agent("/root/critic", "running")];
    await act(async () => jest.advanceTimersByTimeAsync(5000));
    expect(screen.queryByText("poet")).toBeNull();
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
  expect(screen.getByText("Agents · 1 running")).toBeVisible();
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
  const file = PUBLISHED_FILE;
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

test("a page without a Files panel leaves the files out of the card", async () => {
  serve([agent("/root/poet", "running")], {
    ...STATUS,
    has_active_subagents: true,
  });
  showReply([
    {
      placement: { turn_index: 0, tab_index: 0 },
      obj: {
        type: PacketType.PUBLISH_FILES_END,
        files: [PUBLISHED_FILE],
        error: null,
      },
    },
  ]);
  renderActivity(false);

  const trigger = await screen.findByRole("button", { name: "Activity" });
  act(() => trigger.click());
  expect(screen.getByText("poet")).toBeVisible();
  expect(screen.queryByText("View 1 file")).toBeNull();
});

test("files alone do not show the toggle on a page without a Files panel", async () => {
  serve([]);
  showReply([
    {
      placement: { turn_index: 0, tab_index: 0 },
      obj: {
        type: PacketType.PUBLISH_FILES_END,
        files: [PUBLISHED_FILE],
        error: null,
      },
    },
  ]);
  const view = renderActivity(false);
  await act(async () => undefined);
  expect(view.container).toBeEmptyDOMElement();
});

// The run's start in the past, as an ISO date
function startedAgo(ms: number): string {
  return new Date(Date.now() - ms).toISOString();
}

test("a run that started just before the card mounted opens it, as in a new chat", async () => {
  serve(
    [{ ...agent("/root/poet", "running"), started_at: startedAgo(2_000) }],
    {
      ...STATUS,
      has_active_subagents: true,
    }
  );
  renderActivity();
  expect(await screen.findByText("poet")).toBeVisible();
});

test("agents that started well before the chat loads leave the card closed", async () => {
  serve(
    [{ ...agent("/root/poet", "running"), started_at: startedAgo(60_000) }],
    {
      ...STATUS,
      has_active_subagents: true,
    }
  );
  renderActivity();
  await screen.findByRole("button", { name: "Activity" });
  await act(async () => undefined);
  expect(screen.queryByText("poet")).toBeNull();
});

test("an empty list cached from an earlier visit does not open the card for agents already live", async () => {
  serve(
    [{ ...agent("/root/poet", "running"), started_at: startedAgo(60_000) }],
    {
      ...STATUS,
      has_active_subagents: true,
    }
  );
  // The cache still holds the chat as it was before its agents started
  render(
    <AppWorkspaceElementsContext.Provider
      value={{
        workspace: { current: null },
        page: { current: null },
        panelToggleSlot: null,
        activitySlot: document.body,
      }}
    >
      <ChatActivity sessionId="s" />
    </AppWorkspaceElementsContext.Provider>,
    {
      swrConfig: {
        fallback: {
          "/api/chat/chat-session/s/status": STATUS,
          [unstable_serialize([
            "/api/chat/chat-session/s/agents",
            false,
            null,
          ])]: [],
        },
      },
    }
  );
  await screen.findByRole("button", { name: "Activity" });
  await act(async () => undefined);
  expect(screen.queryByText("poet")).toBeNull();
});

test("each live agent has its own Stop, which stops only that agent", async () => {
  serve([agent("/root/poet", "running"), agent("/root/critic", "running")], {
    ...STATUS,
    has_active_subagents: true,
  });
  renderActivity();
  const trigger = await screen.findByRole("button", { name: "Activity" });
  act(() => trigger.click());
  const fetchSpy = jest.mocked(global.fetch);
  await act(async () =>
    screen.getByRole("button", { name: "Stop poet" }).click()
  );

  const stops = fetchSpy.mock.calls.filter(([url]) =>
    String(url).endsWith("/stop-subagents")
  );
  expect(stops).toHaveLength(1);
  expect(String(stops[0]?.[0])).toBe("/api/chat/chat-session/s/stop-subagents");
  expect(stops[0]?.[1]?.method).toBe("POST");
  expect(stops[0]?.[1]?.body).toBe(JSON.stringify({ agent_id: "/root/poet" }));
  expect(screen.getByRole("button", { name: "Stop critic" })).toBeVisible();
  // Stop does not open the agent
  expect(shownSubagent()).toBeNull();
});

test("an agent row opens the agent in the main view", async () => {
  serve([agent("/root/poet", "running")], {
    ...STATUS,
    has_active_subagents: true,
  });
  renderActivity();
  const trigger = await screen.findByRole("button", { name: "Activity" });
  act(() => trigger.click());
  act(() => screen.getByText("poet").click());

  expect(shownSubagent()).toBe("/root/poet");
  // The output panel opens no tab for it
  expect(
    useChatSessionStore.getState().sessions.get("s")?.rightPanel.mode
  ).toBe("closed");
});

test("a page without subagent links, as the extension's, opens no agent from its row", async () => {
  serve([agent("/root/poet", "running")], {
    ...STATUS,
    has_active_subagents: true,
  });
  render(
    <SubagentLinksContext.Provider value={false}>
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
    </SubagentLinksContext.Provider>
  );
  const trigger = await screen.findByRole("button", { name: "Activity" });
  act(() => trigger.click());
  act(() => screen.getByText("poet").click());

  expect(shownSubagent()).toBeNull();
  // Its Stop still works
  expect(screen.getByRole("button", { name: "Stop poet" })).toBeInTheDocument();
});

test("a live agent shows its run time and no status word; a finished one its outcome only", async () => {
  serve(
    [
      { ...agent("/root/poet", "running"), started_at: startedAgo(65_000) },
      {
        ...agent("/root/researcher", "complete"),
        started_at: startedAgo(90_000),
      },
    ],
    { ...STATUS, has_active_subagents: true }
  );
  renderActivity();
  const trigger = await screen.findByRole("button", { name: "Activity" });
  act(() => trigger.click());
  expect(await screen.findByText("1m 5s")).toBeVisible();
  expect(screen.queryByText("Running")).toBeNull();
  // The Stop's tooltip names the action; its label names the agent
  expect(screen.getByRole("button", { name: "Stop poet" })).toBeInTheDocument();
  // A finished agent has no Stop and no time
  act(() => screen.getByRole("button", { name: /Previous agents/ }).click());
  expect(screen.getByText("Done")).toBeVisible();
  expect(screen.queryByText("1m 30s")).toBeNull();
  expect(screen.queryByRole("button", { name: "Stop researcher" })).toBeNull();
});

test("a cached agent list is not the baseline after a failed read", async () => {
  jest
    .spyOn(global, "fetch")
    .mockImplementation(async (input) =>
      String(input).endsWith("/agents")
        ? new Response("boom", { status: 500 })
        : new Response(
            JSON.stringify({ ...STATUS, has_active_subagents: true }),
            { status: 200 }
          )
    );
  let loaded: boolean | null = null;
  function Probe() {
    loaded = useChatSubagents("s", false).loaded;
    return null;
  }
  render(<Probe />, {
    swrConfig: {
      shouldRetryOnError: false,
      fallback: {
        [unstable_serialize(["/api/chat/chat-session/s/agents", true, null])]: [
          agent("/root/poet", "running"),
        ],
      },
    },
  });
  await waitFor(() =>
    expect(
      jest
        .mocked(global.fetch)
        .mock.calls.some(([input]) => String(input).endsWith("/agents"))
    ).toBe(true)
  );
  await act(async () => undefined);
  expect(loaded).toBe(false);
});
