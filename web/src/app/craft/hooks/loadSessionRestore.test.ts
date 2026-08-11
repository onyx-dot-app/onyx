import {
  useBuildSessionStore,
  waitForWebappReady,
} from "@/app/craft/hooks/useBuildSessionStore";
import * as api from "@/app/craft/services/apiServices";

jest.mock("@/app/craft/services/apiServices");

const mockedApi = api as jest.Mocked<typeof api>;

const SESSION_ID = "11111111-1111-1111-1111-111111111111";

// Minimal DetailedSessionResponse shapes — loadSession only reads status,
// session_loaded_in_sandbox, nextjs_port, and sandbox.status.
function sleepingSession(): unknown {
  return {
    id: SESSION_ID,
    status: "idle",
    nextjs_port: null,
    session_loaded_in_sandbox: false,
    sandbox: { id: "sb1", status: "sleeping" },
  };
}

function runningSession(
  nextjsPort: number | null = null
): Record<string, unknown> {
  return {
    id: SESSION_ID,
    status: "active",
    nextjs_port: nextjsPort,
    session_loaded_in_sandbox: true,
    sandbox: { id: "sb1", status: "running" },
  };
}

function webappInfo(has_webapp: boolean | null, ready: boolean): unknown {
  return { has_webapp, webapp_url: null, status: "running", ready };
}

describe("loadSession restore status", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useBuildSessionStore.setState({
      sessions: new Map(),
      currentSessionId: null,
    } as never);
    mockedApi.fetchMessages.mockResolvedValue([] as never);
    mockedApi.fetchActiveTurn.mockResolvedValue(null as never);
    mockedApi.fetchArtifacts.mockResolvedValue([] as never);
    // Default: webapp already serving, so the readiness gate is a no-op.
    mockedApi.fetchWebappInfo.mockResolvedValue(
      webappInfo(true, true) as never
    );
  });

  it("keeps the sandbox running when the post-restore artifact fetch fails", async () => {
    mockedApi.fetchSession.mockResolvedValue(sleepingSession() as never);
    mockedApi.restoreSession.mockResolvedValue(runningSession() as never);
    // Artifacts list the sandbox via opencode-serve and can fail right after
    // the pod comes up — this must NOT flip the sandbox to "failed".
    mockedApi.fetchArtifacts.mockRejectedValue(new Error("opencode not ready"));

    await useBuildSessionStore.getState().loadSession(SESSION_ID);

    const session = useBuildSessionStore.getState().sessions.get(SESSION_ID);
    expect(session?.sandbox?.status).toBe("running");
  });

  it("builds the webapp URL from the session port", async () => {
    mockedApi.fetchSession.mockResolvedValue(runningSession(3210) as never);
    mockedApi.fetchArtifacts.mockResolvedValue([{ type: "web_app" }] as never);

    await useBuildSessionStore.getState().loadSession(SESSION_ID);

    expect(
      useBuildSessionStore.getState().sessions.get(SESSION_ID)?.webappUrl
    ).toBe("http://localhost:3210");
  });

  it("marks the sandbox failed when restore itself fails", async () => {
    mockedApi.fetchSession.mockResolvedValue(sleepingSession() as never);
    mockedApi.restoreSession.mockRejectedValue(new Error("restore boom"));

    await useBuildSessionStore.getState().loadSession(SESSION_ID);

    const session = useBuildSessionStore.getState().sessions.get(SESSION_ID);
    expect(session?.sandbox?.status).toBe("failed");
  });

  it("waits for the webapp before flipping to running, then shows running", async () => {
    mockedApi.fetchSession.mockResolvedValue(sleepingSession() as never);
    mockedApi.restoreSession.mockResolvedValue(runningSession() as never);
    // Webapp not ready on the first poll, ready on the second.
    mockedApi.fetchWebappInfo
      .mockResolvedValueOnce(webappInfo(true, false) as never)
      .mockResolvedValue(webappInfo(true, true) as never);

    await useBuildSessionStore.getState().loadSession(SESSION_ID);

    // It consulted webapp readiness, and the final state is running.
    expect(mockedApi.fetchWebappInfo).toHaveBeenCalled();
    const session = useBuildSessionStore.getState().sessions.get(SESSION_ID);
    expect(session?.sandbox?.status).toBe("running");
  });

  it("remounts the preview on restore, while edits only refresh (HMR handles them)", async () => {
    mockedApi.fetchSession.mockResolvedValue(sleepingSession() as never);
    mockedApi.restoreSession.mockResolvedValue(runningSession() as never);

    await useBuildSessionStore.getState().loadSession(SESSION_ID);

    let session = useBuildSessionStore.getState().sessions.get(SESSION_ID);
    expect(session?.webappNeedsRefresh).toBe(1);
    expect(session?.webappNeedsRemount).toBe(1);

    // A web/ file edit mid-turn must not remount the iframe.
    useBuildSessionStore.getState().triggerWebappRefresh(SESSION_ID);
    session = useBuildSessionStore.getState().sessions.get(SESSION_ID);
    expect(session?.webappNeedsRefresh).toBe(2);
    expect(session?.webappNeedsRemount).toBe(1);
  });

  it("renders a persisted turn-error row when it is the latest activity", async () => {
    mockedApi.fetchSession.mockResolvedValue(runningSession() as never);
    mockedApi.fetchMessages.mockResolvedValue([
      {
        id: "user-1",
        type: "user",
        content: "Do a thing",
        timestamp: new Date(),
        message_metadata: {
          type: "user_message",
          content: { type: "text", text: "Do a thing" },
        },
      },
      {
        id: "error-1",
        type: "assistant",
        content: "",
        timestamp: new Date(),
        message_metadata: {
          type: "error",
          message: "This turn was stopped after reaching its time limit.",
        },
      },
    ] as never);

    await useBuildSessionStore.getState().loadSession(SESSION_ID);

    const session = useBuildSessionStore.getState().sessions.get(SESSION_ID);
    const assistant = session?.messages.find((message) => {
      return message.type === "assistant";
    });
    expect(assistant?.message_metadata?.streamItems).toEqual([
      {
        type: "error",
        id: "error-1",
        content: "This turn was stopped after reaching its time limit.",
      },
    ]);
  });

  it("drops a persisted turn-error row once later activity exists", async () => {
    mockedApi.fetchSession.mockResolvedValue(runningSession() as never);
    mockedApi.fetchMessages.mockResolvedValue([
      {
        id: "user-1",
        type: "user",
        content: "Do a thing",
        timestamp: new Date(),
        message_metadata: {
          type: "user_message",
          content: { type: "text", text: "Do a thing" },
        },
      },
      {
        id: "error-1",
        type: "assistant",
        content: "",
        timestamp: new Date(),
        message_metadata: {
          type: "error",
          message: "This turn was stopped after reaching its time limit.",
        },
      },
      {
        id: "user-2",
        type: "user",
        content: "Continue",
        timestamp: new Date(),
        message_metadata: {
          type: "user_message",
          content: { type: "text", text: "Continue" },
        },
      },
      {
        id: "answer-2",
        type: "assistant",
        content: "",
        timestamp: new Date(),
        message_metadata: {
          type: "agent_message",
          content: { type: "text", text: "Continued and finished." },
        },
      },
    ] as never);

    await useBuildSessionStore.getState().loadSession(SESSION_ID);

    const session = useBuildSessionStore.getState().sessions.get(SESSION_ID);
    const allItems = (session?.messages ?? [])
      .filter((message) => message.type === "assistant")
      .flatMap(
        (message) =>
          (message.message_metadata?.streamItems ?? []) as { type: string }[]
      );
    expect(allItems.some((item) => item.type === "error")).toBe(false);
    expect(allItems.some((item) => item.type === "text")).toBe(true);
  });

  it("restores persisted agent thought packets as collapsed transcript stream items", async () => {
    mockedApi.fetchSession.mockResolvedValue(runningSession() as never);
    mockedApi.fetchMessages.mockResolvedValue([
      {
        id: "user-1",
        type: "user",
        content: "Build a dashboard",
        timestamp: new Date(),
        message_metadata: {
          type: "user_message",
          content: { type: "text", text: "Build a dashboard" },
        },
      },
      {
        id: "thought-1",
        type: "assistant",
        content: "",
        timestamp: new Date(),
        message_metadata: {
          type: "agent_thought",
          content: { type: "text", text: "Inspecting available files." },
        },
      },
      {
        id: "answer-1",
        type: "assistant",
        content: "",
        timestamp: new Date(),
        message_metadata: {
          type: "agent_message",
          content: { type: "text", text: "Created the dashboard." },
        },
      },
    ] as never);

    await useBuildSessionStore.getState().loadSession(SESSION_ID);

    const session = useBuildSessionStore.getState().sessions.get(SESSION_ID);
    const assistant = session?.messages.find((message) => {
      return message.type === "assistant";
    });
    const streamItems = assistant?.message_metadata?.streamItems;

    expect(streamItems).toEqual([
      {
        type: "thinking",
        id: "thought-1",
        content: "Inspecting available files.",
        isStreaming: false,
      },
      {
        type: "text",
        id: "answer-1",
        content: "Created the dashboard.",
        isStreaming: false,
      },
    ]);
  });

  it("keeps child-routed text and thinking out of the parent transcript", async () => {
    mockedApi.fetchSession.mockResolvedValue(runningSession() as never);
    mockedApi.fetchMessages.mockResolvedValue([
      {
        id: "user-1",
        type: "user",
        content: "Build a dashboard",
        timestamp: new Date(),
        message_metadata: {
          type: "user_message",
          content: { type: "text", text: "Build a dashboard" },
        },
      },
      {
        id: "child-thought-1",
        type: "assistant",
        content: "",
        timestamp: new Date(),
        message_metadata: {
          type: "agent_thought",
          content: { type: "text", text: "Child thinking." },
          _meta: {
            sessionId: "child-session-1",
            parentSessionId: SESSION_ID,
          },
        },
      },
      {
        id: "child-answer-1",
        type: "assistant",
        content: "",
        timestamp: new Date(),
        message_metadata: {
          type: "agent_message",
          content: { type: "text", text: "Child answer." },
          _meta: {
            sessionId: "child-session-1",
            parentSessionId: SESSION_ID,
          },
        },
      },
    ] as never);

    await useBuildSessionStore.getState().loadSession(SESSION_ID);

    const session = useBuildSessionStore.getState().sessions.get(SESSION_ID);
    expect(session?.messages).toEqual([
      expect.objectContaining({ id: "user-1", type: "user" }),
    ]);
    expect(session?.subagents.get("child-session-1")?.turns[0]).toMatchObject({
      thinking: "Child thinking.",
      response: "Child answer.",
      streamItems: [
        expect.objectContaining({
          type: "thinking",
          content: "Child thinking.",
          isStreaming: false,
        }),
        expect.objectContaining({
          type: "text",
          content: "Child answer.",
          isStreaming: false,
        }),
      ],
    });
  });

  it("restores subagent prompt and logs when parent task output carries the child id", async () => {
    mockedApi.fetchSession.mockResolvedValue(runningSession() as never);
    mockedApi.fetchMessages.mockResolvedValue([
      {
        id: "user-1",
        type: "user",
        content: "Build a game",
        timestamp: new Date(),
        message_metadata: {
          type: "user_message",
          content: { type: "text", text: "Build a game" },
        },
      },
      {
        id: "child-thought-1",
        type: "assistant",
        content: "",
        timestamp: new Date(),
        message_metadata: {
          type: "agent_thought",
          content: { type: "text", text: "Child thinking." },
          _meta: {
            sessionId: "child-session-1",
            parentSessionId: SESSION_ID,
          },
        },
      },
      {
        id: "child-answer-1",
        type: "assistant",
        content: "",
        timestamp: new Date(),
        message_metadata: {
          type: "agent_message",
          content: { type: "text", text: "Child answer." },
          _meta: {
            sessionId: "child-session-1",
            parentSessionId: SESSION_ID,
          },
        },
      },
      {
        id: "task-progress-1",
        type: "assistant",
        content: "",
        timestamp: new Date(),
        message_metadata: {
          type: "tool_call_progress",
          tool_call_id: "task-call-1",
          kind: "task",
          status: "completed",
          raw_input: {
            description: "Build Space Invaders game",
            prompt:
              "You are building ONE retro arcade game as a single React component.",
          },
          raw_output: {
            output:
              "task_id: child-session-1 (for resuming to continue this task if needed)\n\n<task_result>Child answer.</task_result>",
          },
        },
      },
    ] as never);

    await useBuildSessionStore.getState().loadSession(SESSION_ID);

    const session = useBuildSessionStore.getState().sessions.get(SESSION_ID);
    expect(session?.subagents.get("child-session-1")).toMatchObject({
      parentToolCallId: "task-call-1",
      name: "Build Space Invaders game",
      status: "done",
      turns: [
        expect.objectContaining({
          prompt:
            "You are building ONE retro arcade game as a single React component.",
          thinking: "Child thinking.",
          response: "Child answer.",
          streamItems: [
            expect.objectContaining({ type: "thinking" }),
            expect.objectContaining({ type: "text", content: "Child answer." }),
          ],
        }),
      ],
    });

    const assistant = session?.messages.find(
      (message) => message.type === "assistant"
    );
    expect(assistant?.message_metadata?.streamItems).toEqual([
      expect.objectContaining({
        type: "tool_call",
        id: "task-call-1",
      }),
    ]);
  });

  it("preserves live turn metadata when active turn lookup fails", async () => {
    mockedApi.fetchSession.mockResolvedValue(runningSession() as never);
    mockedApi.fetchActiveTurn.mockRejectedValue(
      new Error("turn endpoint unavailable")
    );
    useBuildSessionStore.getState().createSession(SESSION_ID, {
      status: "running",
      messages: [
        {
          id: "local-user",
          type: "user",
          content: "hello",
          timestamp: new Date(),
        },
      ],
      activeTurnId: "turn-live",
      activeTurnLocalOwner: false,
      isLoaded: false,
    });

    await useBuildSessionStore
      .getState()
      .loadSession(SESSION_ID, { force: true });

    const session = useBuildSessionStore.getState().sessions.get(SESSION_ID);
    expect(session?.status).toBe("running");
    expect(session?.activeTurnId).toBe("turn-live");
    expect(session?.activeTurnLocalOwner).toBe(false);
  });

  it("preserves stale-skill state while loading a pre-provisioned turn", async () => {
    mockedApi.fetchSession.mockResolvedValue({
      ...runningSession(),
      skills_stale: true,
    } as never);
    useBuildSessionStore.getState().createSession(SESSION_ID, {
      status: "running",
      messages: [
        {
          id: "local-user",
          type: "user",
          content: "hello",
          timestamp: new Date(),
        },
      ],
      skillsStale: false,
      isLoaded: false,
    });

    await useBuildSessionStore
      .getState()
      .loadSession(SESSION_ID, { force: true });

    expect(
      useBuildSessionStore.getState().sessions.get(SESSION_ID)?.skillsStale
    ).toBe(false);
  });

  it("clears stale turn metadata when active turn lookup says no turn is running", async () => {
    mockedApi.fetchSession.mockResolvedValue(runningSession() as never);
    mockedApi.fetchActiveTurn.mockResolvedValue(null as never);
    useBuildSessionStore.getState().createSession(SESSION_ID, {
      status: "running",
      activeTurnId: "turn-stale",
      activeTurnLocalOwner: false,
      isLoaded: false,
    });

    await useBuildSessionStore
      .getState()
      .loadSession(SESSION_ID, { force: true });

    const session = useBuildSessionStore.getState().sessions.get(SESSION_ID);
    expect(session?.status).toBe("active");
    expect(session?.activeTurnId).toBeNull();
    expect(session?.activeTurnLocalOwner).toBe(false);
  });
});

describe("loadSession preferPersisted (interrupt reconciliation)", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useBuildSessionStore.setState({
      sessions: new Map(),
      currentSessionId: null,
    } as never);
    mockedApi.fetchActiveTurn.mockResolvedValue(null as never);
    mockedApi.fetchArtifacts.mockResolvedValue([] as never);
    mockedApi.fetchWebappInfo.mockResolvedValue(
      webappInfo(true, true) as never
    );
    mockedApi.fetchSession.mockResolvedValue(runningSession() as never);
  });

  function seedInterruptedSession(): void {
    useBuildSessionStore.getState().createSession(SESSION_ID, {
      status: "running",
      messages: [
        {
          id: "local-user",
          type: "user",
          content: "Write an essay",
          timestamp: new Date(),
        },
      ],
      activeTurnId: "turn-interrupted",
      activeTurnIndex: 0,
      activeTurnLocalOwner: true,
      isLoaded: false,
    });
    mockedApi.fetchMessages.mockResolvedValue([
      {
        id: "user-1",
        type: "user",
        content: "Write an essay",
        timestamp: new Date(),
        message_metadata: {
          type: "user_message",
          content: { type: "text", text: "Write an essay" },
        },
      },
      {
        id: "thought-1",
        type: "assistant",
        content: "",
        timestamp: new Date(),
        message_metadata: {
          type: "agent_thought",
          content: { type: "text", text: "Planning the essay structure." },
        },
      },
    ] as never);
  }

  it("rehydrates the persisted interrupted transcript while keeping status running", async () => {
    seedInterruptedSession();

    await useBuildSessionStore
      .getState()
      .loadSession(SESSION_ID, { force: true, preferPersisted: true });

    const session = useBuildSessionStore.getState().sessions.get(SESSION_ID);
    expect(session?.status).toBe("running");
    const assistant = session?.messages.find((m) => m.type === "assistant");
    expect(assistant?.message_metadata?.streamItems).toEqual([
      {
        type: "thinking",
        id: "thought-1",
        content: "Planning the essay structure.",
        isStreaming: false,
      },
    ]);
    expect(session?.streamItems).toEqual([]);
    expect(session?.activeTurnId).toBeNull();
    expect(session?.activeTurnLocalOwner).toBe(false);
  });

  it("reconciles stale skills when an interrupted turn settles", async () => {
    seedInterruptedSession();
    mockedApi.fetchSession.mockResolvedValue({
      ...runningSession(),
      skills_stale: true,
    } as never);

    await useBuildSessionStore
      .getState()
      .loadSession(SESSION_ID, { force: true, preferPersisted: true });

    expect(
      useBuildSessionStore.getState().sessions.get(SESSION_ID)?.skillsStale
    ).toBe(true);
  });

  it("keeps the stale local transcript without preferPersisted (the bug)", async () => {
    seedInterruptedSession();

    await useBuildSessionStore
      .getState()
      .loadSession(SESSION_ID, { force: true });

    const session = useBuildSessionStore.getState().sessions.get(SESSION_ID);
    expect(session?.messages).toEqual([
      expect.objectContaining({ id: "local-user", type: "user" }),
    ]);
  });
});

describe("waitForWebappReady", () => {
  beforeEach(() => jest.clearAllMocks());
  afterEach(() => jest.clearAllMocks());

  it("returns immediately when the session has no webapp", async () => {
    mockedApi.fetchWebappInfo.mockResolvedValue(
      webappInfo(false, false) as never
    );
    await waitForWebappReady(SESSION_ID, { intervalMs: 0 });
    expect(mockedApi.fetchWebappInfo).toHaveBeenCalledTimes(1);
  });

  it("returns immediately when the webapp is already ready", async () => {
    mockedApi.fetchWebappInfo.mockResolvedValue(
      webappInfo(true, true) as never
    );
    await waitForWebappReady(SESSION_ID, { intervalMs: 0 });
    expect(mockedApi.fetchWebappInfo).toHaveBeenCalledTimes(1);
  });

  it("polls until the webapp reports ready", async () => {
    mockedApi.fetchWebappInfo
      .mockResolvedValueOnce(webappInfo(true, false) as never)
      .mockResolvedValueOnce(webappInfo(true, false) as never)
      .mockResolvedValue(webappInfo(true, true) as never);
    await waitForWebappReady(SESSION_ID, { intervalMs: 0 });
    expect(mockedApi.fetchWebappInfo).toHaveBeenCalledTimes(3);
  });

  it("gives up after maxAttempts when the webapp never comes up", async () => {
    mockedApi.fetchWebappInfo.mockResolvedValue(
      webappInfo(true, false) as never
    );
    await waitForWebappReady(SESSION_ID, { intervalMs: 0, maxAttempts: 3 });
    expect(mockedApi.fetchWebappInfo).toHaveBeenCalledTimes(3);
  });

  it("keeps polling through transient fetch errors", async () => {
    mockedApi.fetchWebappInfo
      .mockRejectedValueOnce(new Error("sandbox not reachable"))
      .mockResolvedValue(webappInfo(true, true) as never);
    await waitForWebappReady(SESSION_ID, { intervalMs: 0 });
    expect(mockedApi.fetchWebappInfo).toHaveBeenCalledTimes(2);
  });

  it("keeps polling while webapp existence is unknown", async () => {
    mockedApi.fetchWebappInfo
      .mockResolvedValueOnce(webappInfo(null, false) as never)
      .mockResolvedValue(webappInfo(false, false) as never);
    await waitForWebappReady(SESSION_ID, { intervalMs: 0 });
    expect(mockedApi.fetchWebappInfo).toHaveBeenCalledTimes(2);
  });
});
