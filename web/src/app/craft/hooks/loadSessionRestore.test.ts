/** @jest-environment jsdom */
import { act, waitFor } from "@tests/setup/test-utils";
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
function sleepingSession(): Record<string, unknown> {
  return {
    id: SESSION_ID,
    status: "idle",
    skills_stale: false,
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
    skills_stale: false,
    nextjs_port: nextjsPort,
    session_loaded_in_sandbox: true,
    sandbox: { id: "sb1", status: "running" },
  };
}

function webappInfo(has_webapp: boolean | null, ready: boolean): unknown {
  return { has_webapp, webapp_url: null, status: "running", ready };
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve: (value: T) => void = () => {};
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
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
    mockedApi.fetchOutputInventory.mockResolvedValue({
      files: [],
      complete: true,
    });
    // Default: webapp already serving, so the readiness gate is a no-op.
    mockedApi.fetchWebappInfo.mockResolvedValue(
      webappInfo(true, true) as never
    );
  });

  it("loads the session while its inventory is still pending", async () => {
    mockedApi.fetchSession.mockResolvedValue(runningSession() as never);
    const inventory =
      deferred<Awaited<ReturnType<typeof api.fetchOutputInventory>>>();
    mockedApi.fetchOutputInventory.mockReturnValueOnce(inventory.promise);
    await useBuildSessionStore.getState().loadSession(SESSION_ID);
    expect(
      useBuildSessionStore.getState().sessions.get(SESSION_ID)
    ).toMatchObject({
      isLoaded: true,
      outputInventory: null,
    });
    inventory.resolve({ files: [], complete: true });
    // Wait for the serialized queue to settle before resetting the store.
    await useBuildSessionStore
      .getState()
      .refreshOutputInventory(SESSION_ID, { silent: true });
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

  it("clears stale skills after a successful session restore", async () => {
    mockedApi.fetchSession.mockResolvedValue({
      ...sleepingSession(),
      skills_stale: true,
    } as never);
    mockedApi.restoreSession.mockResolvedValue({
      ...runningSession(),
      skills_stale: false,
    } as never);

    await useBuildSessionStore.getState().loadSession(SESSION_ID);

    expect(
      useBuildSessionStore.getState().sessions.get(SESSION_ID)?.skillsStale
    ).toBe(false);
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

  it("retains fetched stale-skill state during a pre-provisioned turn", async () => {
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
    ).toBe(true);
  });

  it("rejects a load fetched before a newer stale-skill update", async () => {
    const messages = deferred<unknown[]>();
    mockedApi.fetchSession.mockResolvedValue({
      ...runningSession(),
      skills_stale: true,
    } as never);
    mockedApi.fetchMessages.mockReturnValue(messages.promise as never);

    const load = useBuildSessionStore
      .getState()
      .loadSession(SESSION_ID, { force: true });
    await Promise.resolve();
    expect(mockedApi.fetchMessages).toHaveBeenCalled();

    useBuildSessionStore
      .getState()
      .updateSessionData(SESSION_ID, { skillsStale: false });
    messages.resolve([]);
    await load;

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

  it("shows persisted history before runtime discovery completes", async () => {
    const runtime = deferred<Awaited<ReturnType<typeof api.fetchSession>>>();
    mockedApi.fetchSession.mockReturnValueOnce(runtime.promise);
    mockedApi.fetchMessages.mockResolvedValueOnce([
      {
        id: "persisted-user",
        type: "user",
        content: "Saved conversation",
        created_at: "2026-10-09T00:00:00Z",
      },
    ] as never);
    mockedApi.restoreSession.mockResolvedValueOnce(runningSession() as never);
    const loading = useBuildSessionStore.getState().loadSession(SESSION_ID);

    await waitFor(() => {
      const session = useBuildSessionStore.getState().sessions.get(SESSION_ID);
      expect(session?.isLoaded).toBe(false);
      expect(session?.messages[0]?.content).toBe("Saved conversation");
    });
    expect(mockedApi.restoreSession).not.toHaveBeenCalled();
    expect(mockedApi.fetchArtifacts).not.toHaveBeenCalled();
    expect(
      useBuildSessionStore.getState().sessions.get(SESSION_ID)?.sandbox
    ).toBeNull();

    runtime.resolve({
      ...sleepingSession(),
      agent_provider: "saved-provider",
      agent_model: "saved-model",
    } as never);
    await loading;
    expect(mockedApi.restoreSession).toHaveBeenCalledWith(SESSION_ID);
    expect(
      useBuildSessionStore.getState().sessions.get(SESSION_ID)
    ).toMatchObject({
      isLoaded: true,
      agentProvider: "saved-provider",
      agentModel: "saved-model",
      sandbox: { status: "running" },
      filesNeedsRefresh: 1,
    });
  });

  it.each([
    ["running", "history"],
    ["failed", "history"],
    ["running", "runtime"],
    ["failed", "runtime"],
  ] as const)(
    "finishes metadata loading without replacing a newer %s turn started during %s loading",
    async (status, stage) => {
      const runtime = deferred<Awaited<ReturnType<typeof api.fetchSession>>>();
      const history = deferred<Awaited<ReturnType<typeof api.fetchMessages>>>();
      mockedApi.fetchSession.mockReturnValueOnce(runtime.promise);
      mockedApi.fetchMessages.mockReturnValueOnce(history.promise);
      const loading = useBuildSessionStore.getState().loadSession(SESSION_ID);
      await waitFor(() => expect(mockedApi.fetchMessages).toHaveBeenCalled());
      if (stage === "runtime") await act(async () => history.resolve([]));
      useBuildSessionStore.getState().updateSessionData(SESSION_ID, {
        turnGeneration: 1,
        status,
        error: status === "failed" ? "Send rejected" : null,
        activeTurnId: status === "running" ? "new-turn" : null,
        messages: [
          {
            id: "local",
            type: "user",
            content: "New prompt",
            timestamp: new Date(),
          },
        ],
      });
      history.resolve([]);
      runtime.resolve({
        ...runningSession(),
        agent_provider: "saved-provider",
        agent_model: "saved-model",
      } as never);
      await loading;
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)
      ).toMatchObject({
        isLoaded: true,
        loadError: null,
        agentModel: "saved-model",
        status,
        error: status === "failed" ? "Send rejected" : null,
        activeTurnId: status === "running" ? "new-turn" : null,
        messages: [{ content: "New prompt" }],
        sandbox: { status: "running" },
      });
      expect(mockedApi.fetchArtifacts).toHaveBeenCalled();
    }
  );

  it("keeps a rejected prompt and turn error when revisiting a loaded session", async () => {
    mockedApi.fetchSession.mockResolvedValue(runningSession() as never);
    await useBuildSessionStore.getState().loadSession(SESSION_ID);
    useBuildSessionStore.getState().updateSessionData(SESSION_ID, {
      status: "active",
      error: "Token budget exceeded",
      messages: [
        {
          id: "rejected",
          type: "user",
          content: "Keep this prompt",
          timestamp: new Date(),
        },
      ],
      streamItems: [
        { type: "error", id: "budget-error", content: "Token budget exceeded" },
      ],
    });
    const rejected = useBuildSessionStore.getState().sessions.get(SESSION_ID);
    useBuildSessionStore.getState().setCurrentSession("another-session");
    await useBuildSessionStore.getState().loadSession(SESSION_ID);
    expect(mockedApi.fetchSession).toHaveBeenCalledTimes(1);
    expect(mockedApi.fetchMessages).toHaveBeenCalledTimes(1);
    const revisited = useBuildSessionStore.getState().sessions.get(SESSION_ID);
    expect(revisited?.messages).toBe(rejected?.messages);
    expect(revisited?.streamItems).toBe(rejected?.streamItems);
    expect(revisited?.error).toBe("Token budget exceeded");
  });

  it("retains loaded history after runtime discovery fails and retries on revisit", async () => {
    mockedApi.fetchSession
      .mockRejectedValueOnce(new Error("Runtime unavailable"))
      .mockResolvedValueOnce(runningSession() as never);
    mockedApi.fetchMessages.mockResolvedValue([
      {
        id: "persisted-user",
        type: "user",
        content: "Saved conversation",
        created_at: "2026-10-09T00:00:00Z",
      },
    ] as never);
    await useBuildSessionStore.getState().loadSession(SESSION_ID);
    expect(
      useBuildSessionStore.getState().sessions.get(SESSION_ID)
    ).toMatchObject({
      isLoaded: false,
      error: null,
      loadError: "Runtime unavailable",
    });
    expect(
      useBuildSessionStore.getState().sessions.get(SESSION_ID)?.messages[0]
        ?.content
    ).toBe("Saved conversation");

    useBuildSessionStore.getState().setCurrentSession("another-session");
    await useBuildSessionStore.getState().loadSession(SESSION_ID);
    expect(mockedApi.fetchSession).toHaveBeenCalledTimes(2);
    expect(
      useBuildSessionStore.getState().sessions.get(SESSION_ID)
    ).toMatchObject({
      isLoaded: true,
      error: null,
      loadError: null,
      sandbox: { status: "running" },
    });
  });

  it("invalidates even an empty directory cache only after restoration finishes", async () => {
    mockedApi.fetchSession.mockResolvedValue(sleepingSession() as never);
    const restore = deferred<Awaited<ReturnType<typeof api.restoreSession>>>();
    const started = deferred<void>();
    mockedApi.restoreSession.mockImplementation(() => {
      started.resolve();
      return restore.promise;
    });
    const loading = useBuildSessionStore.getState().loadSession(SESSION_ID);
    await started.promise;
    expect(
      useBuildSessionStore.getState().sessions.get(SESSION_ID)
    ).toMatchObject({
      sandbox: { status: "restoring" },
      filesNeedsRefresh: 0,
    });
    restore.resolve(runningSession() as never);
    await loading;
    expect(
      useBuildSessionStore.getState().sessions.get(SESSION_ID)
    ).toMatchObject({
      sandbox: { status: "running" },
      filesNeedsRefresh: 1,
    });
  });

  it("keeps newer session data when concurrent force loads finish out of order", async () => {
    const older = deferred<Awaited<ReturnType<typeof api.fetchSession>>>();
    const newer = deferred<Awaited<ReturnType<typeof api.fetchSession>>>();
    mockedApi.fetchSession
      .mockReturnValueOnce(older.promise)
      .mockReturnValueOnce(newer.promise);
    const latestMessages = [
      {
        id: "latest-message",
        type: "user",
        content: "latest transcript",
        created_at: "2026-10-09T00:00:00Z",
      },
    ];
    mockedApi.fetchMessages.mockResolvedValue(latestMessages as never);
    const first = useBuildSessionStore
      .getState()
      .loadSession(SESSION_ID, { force: true });
    const second = useBuildSessionStore
      .getState()
      .loadSession(SESSION_ID, { force: true });
    newer.resolve({ ...runningSession(), agent_model: "new-model" } as never);
    await second;
    const latestSession = useBuildSessionStore
      .getState()
      .sessions.get(SESSION_ID);
    expect(latestSession).toMatchObject({
      agentModel: "new-model",
      sandbox: { status: "running" },
    });
    expect(latestSession?.messages[0]?.content).toBe("latest transcript");

    mockedApi.fetchMessages.mockResolvedValue([]);
    older.resolve({
      ...sleepingSession(),
      agent_model: "old-model",
    } as never);
    await first;
    expect(useBuildSessionStore.getState().sessions.get(SESSION_ID)).toBe(
      latestSession
    );
    expect(mockedApi.restoreSession).not.toHaveBeenCalled();
    expect(mockedApi.fetchMessages).toHaveBeenCalledTimes(1);
  });

  it("ignores runtime discovery for a deleted and recreated session", async () => {
    const runtime = deferred<Awaited<ReturnType<typeof api.fetchSession>>>();
    mockedApi.fetchSession.mockReturnValueOnce(runtime.promise);
    const loading = useBuildSessionStore.getState().loadSession(SESSION_ID);
    await waitFor(() => {
      expect(mockedApi.fetchMessages).toHaveBeenCalled();
    });
    const oldInstance = useBuildSessionStore
      .getState()
      .sessions.get(SESSION_ID)?.instanceId;
    useBuildSessionStore.setState({
      sessions: new Map(),
      currentSessionId: null,
    });
    useBuildSessionStore.getState().createSession(SESSION_ID, {
      isLoaded: true,
      agentModel: "replacement-model",
    });
    const replacement = useBuildSessionStore
      .getState()
      .sessions.get(SESSION_ID);
    expect(replacement?.instanceId).not.toBe(oldInstance);
    runtime.resolve(sleepingSession() as never);
    await loading;
    expect(useBuildSessionStore.getState().sessions.get(SESSION_ID)).toBe(
      replacement
    );
    expect(mockedApi.restoreSession).not.toHaveBeenCalled();
    expect(mockedApi.fetchArtifacts).not.toHaveBeenCalled();
  });

  it("finishes filesystem restoration before the app is ready", async () => {
    mockedApi.fetchSession.mockResolvedValue(sleepingSession() as never);
    mockedApi.restoreSession.mockResolvedValue(runningSession() as never);
    const readiness =
      deferred<Awaited<ReturnType<typeof api.fetchWebappInfo>>>();
    mockedApi.fetchWebappInfo.mockReturnValueOnce(readiness.promise);
    await useBuildSessionStore.getState().loadSession(SESSION_ID);
    expect(
      useBuildSessionStore.getState().sessions.get(SESSION_ID)
    ).toMatchObject({
      sandbox: { status: "running" },
      filesNeedsRefresh: 1,
      webappNeedsRemount: 0,
    });
    expect(mockedApi.fetchOutputInventory).toHaveBeenCalled();
    readiness.resolve(webappInfo(true, true) as never);
    await waitFor(() =>
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)
          ?.webappNeedsRemount
      ).toBe(1)
    );
  });

  it("keeps restored app readiness across a successor load", async () => {
    mockedApi.fetchSession.mockResolvedValueOnce(sleepingSession() as never);
    mockedApi.restoreSession.mockResolvedValueOnce(runningSession() as never);
    const readiness =
      deferred<Awaited<ReturnType<typeof api.fetchWebappInfo>>>();
    mockedApi.fetchWebappInfo.mockReturnValueOnce(readiness.promise);
    await useBuildSessionStore.getState().loadSession(SESSION_ID);
    mockedApi.fetchSession.mockResolvedValueOnce(runningSession() as never);
    await useBuildSessionStore
      .getState()
      .loadSession(SESSION_ID, { force: true });
    expect(mockedApi.restoreSession).toHaveBeenCalledTimes(1);
    expect(
      useBuildSessionStore.getState().sessions.get(SESSION_ID)
        ?.webappNeedsRemount
    ).toBe(0);
    readiness.resolve(webappInfo(true, true) as never);
    await waitFor(() =>
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)
          ?.webappNeedsRemount
      ).toBe(1)
    );
  });

  it("ignores delayed app readiness after the sandbox is replaced", async () => {
    mockedApi.fetchSession.mockResolvedValue(sleepingSession() as never);
    mockedApi.restoreSession.mockResolvedValue(runningSession() as never);
    const readiness =
      deferred<Awaited<ReturnType<typeof api.fetchWebappInfo>>>();
    mockedApi.fetchWebappInfo.mockReturnValueOnce(readiness.promise);
    await useBuildSessionStore.getState().loadSession(SESSION_ID);
    useBuildSessionStore
      .getState()
      .updateSessionData(SESSION_ID, { sandbox: null });
    readiness.resolve(webappInfo(true, true) as never);
    await act(async () => {});
    expect(
      useBuildSessionStore.getState().sessions.get(SESSION_ID)
    ).toMatchObject({ sandbox: null, webappNeedsRemount: 0 });
  });

  it.each(["restore", "readiness"] as const)(
    "finishes %s readiness without replacing a newer turn",
    async (stage) => {
      mockedApi.fetchSession.mockResolvedValue(sleepingSession() as never);
      const restore =
        deferred<Awaited<ReturnType<typeof api.restoreSession>>>();
      const readiness =
        deferred<Awaited<ReturnType<typeof api.fetchWebappInfo>>>();
      mockedApi.restoreSession.mockReturnValueOnce(restore.promise);
      mockedApi.fetchWebappInfo.mockReset();
      mockedApi.fetchWebappInfo.mockReturnValueOnce(readiness.promise);
      const loading = useBuildSessionStore.getState().loadSession(SESSION_ID);
      await waitFor(() => expect(mockedApi.restoreSession).toHaveBeenCalled());
      if (stage === "readiness") {
        restore.resolve(runningSession() as never);
        await waitFor(() =>
          expect(mockedApi.fetchWebappInfo).toHaveBeenCalled()
        );
      }
      useBuildSessionStore.getState().updateSessionData(SESSION_ID, {
        turnGeneration: 1,
        status: "running",
        activeTurnId: "newer-turn",
      });

      restore.resolve(runningSession() as never);
      readiness.resolve(webappInfo(true, true) as never);
      await loading;
      await waitFor(() =>
        expect(
          useBuildSessionStore.getState().sessions.get(SESSION_ID)
            ?.webappNeedsRemount
        ).toBe(1)
      );
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)
      ).toMatchObject({
        status: "running",
        activeTurnId: "newer-turn",
        sandbox: { status: "running" },
        filesNeedsRefresh: 1,
        webappNeedsRemount: 1,
      });
      expect(mockedApi.fetchArtifacts).toHaveBeenCalledTimes(1);
    }
  );

  it("preserves a newer turn when the older restoration fails", async () => {
    mockedApi.fetchSession.mockResolvedValue(sleepingSession() as never);
    let rejectRestore: (error: Error) => void = () => {};
    mockedApi.restoreSession.mockReturnValueOnce(
      new Promise((_, reject) => {
        rejectRestore = reject;
      })
    );
    const loading: Promise<void> = useBuildSessionStore
      .getState()
      .loadSession(SESSION_ID);
    await waitFor(() => expect(mockedApi.restoreSession).toHaveBeenCalled());
    useBuildSessionStore.getState().updateSessionData(SESSION_ID, {
      turnGeneration: 1,
      status: "running",
      activeTurnId: "newer-turn",
    });
    rejectRestore(new Error("Restore unavailable"));
    await loading;
    expect(
      useBuildSessionStore.getState().sessions.get(SESSION_ID)
    ).toMatchObject({
      status: "running",
      activeTurnId: "newer-turn",
      sandbox: { status: "failed" },
    });
  });

  it("retries a failed restoration when the session is revisited", async () => {
    mockedApi.fetchSession.mockResolvedValue(sleepingSession() as never);
    mockedApi.restoreSession
      .mockRejectedValueOnce(new Error("restore unavailable"))
      .mockResolvedValueOnce(runningSession() as never);

    await useBuildSessionStore.getState().loadSession(SESSION_ID);
    expect(
      useBuildSessionStore.getState().sessions.get(SESSION_ID)
    ).toMatchObject({
      isLoaded: true,
      sandbox: { status: "failed" },
    });

    useBuildSessionStore.getState().setCurrentSession("another-session");
    await useBuildSessionStore.getState().loadSession(SESSION_ID);

    expect(mockedApi.restoreSession).toHaveBeenCalledTimes(2);
    expect(
      useBuildSessionStore.getState().sessions.get(SESSION_ID)
    ).toMatchObject({
      isLoaded: true,
      sandbox: { status: "running" },
    });
  });

  it("clears cached stale-skill state when loading a current runtime", async () => {
    mockedApi.fetchSession.mockResolvedValue({
      ...runningSession(),
      skills_stale: false,
    } as never);
    useBuildSessionStore
      .getState()
      .createSession(SESSION_ID, { skillsStale: true, isLoaded: false });
    await useBuildSessionStore
      .getState()
      .loadSession(SESSION_ID, { force: true });
    expect(
      useBuildSessionStore.getState().sessions.get(SESSION_ID)?.skillsStale
    ).toBe(false);
  });
  it("does not let an older history read overwrite a settled transcript", async () => {
    const staleHistory =
      deferred<Awaited<ReturnType<typeof api.fetchMessages>>>();
    mockedApi.fetchSession.mockResolvedValue(runningSession() as never);
    mockedApi.fetchMessages.mockReturnValueOnce(staleHistory.promise);
    const store = useBuildSessionStore.getState();
    store.createSession(SESSION_ID, {
      status: "running",
      isLoaded: true,
      turnGeneration: 1,
    });
    const loading = store.loadSession(SESSION_ID, { force: true });
    await waitFor(() =>
      expect(mockedApi.fetchMessages).toHaveBeenCalledTimes(1)
    );
    mockedApi.fetchMessages.mockResolvedValue([
      {
        id: "confirmed",
        type: "assistant",
        content: "Final answer",
        message_metadata: {
          streamItems: [
            {
              type: "text",
              id: "confirmed-text",
              content: "Final answer",
              isStreaming: false,
            },
          ],
        },
        timestamp: new Date(),
        turn_index: 0,
      },
    ]);
    await store.beginTurnSettlement(SESSION_ID, "completed-turn", 1);
    staleHistory.resolve([]);
    await loading;
    expect(
      useBuildSessionStore.getState().sessions.get(SESSION_ID)?.messages
    ).toEqual([
      expect.objectContaining({ id: "confirmed", content: "Final answer" }),
    ]);
    expect(
      useBuildSessionStore.getState().sessions.get(SESSION_ID)?.turnSettlement
        ?.phase
    ).toBe("ready");
  });
});

describe("waitForWebappReady", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    jest.useFakeTimers();
  });
  afterEach(() => {
    jest.clearAllMocks();
    jest.useRealTimers();
  });

  it("returns immediately when the session has no webapp", async () => {
    mockedApi.fetchWebappInfo.mockResolvedValue(
      webappInfo(false, false) as never
    );
    const pending = waitForWebappReady(SESSION_ID);
    await jest.advanceTimersByTimeAsync(30000);
    await pending;
    expect(mockedApi.fetchWebappInfo).toHaveBeenCalledTimes(1);
  });

  it("returns immediately when the webapp is already ready", async () => {
    mockedApi.fetchWebappInfo.mockResolvedValue(
      webappInfo(true, true) as never
    );
    const pending = waitForWebappReady(SESSION_ID);
    await jest.advanceTimersByTimeAsync(30000);
    await pending;
    expect(mockedApi.fetchWebappInfo).toHaveBeenCalledTimes(1);
  });

  it("polls until the webapp reports ready", async () => {
    mockedApi.fetchWebappInfo
      .mockResolvedValueOnce(webappInfo(true, false) as never)
      .mockResolvedValueOnce(webappInfo(true, false) as never)
      .mockResolvedValue(webappInfo(true, true) as never);
    const pending = waitForWebappReady(SESSION_ID);
    await jest.advanceTimersByTimeAsync(30000);
    await pending;
    expect(mockedApi.fetchWebappInfo).toHaveBeenCalledTimes(3);
  });

  it("stops at the deadline when the webapp never comes up", async () => {
    mockedApi.fetchWebappInfo.mockResolvedValue(
      webappInfo(true, false) as never
    );
    const pending = waitForWebappReady(SESSION_ID);
    await jest.advanceTimersByTimeAsync(30000);
    await expect(pending).resolves.toBe(false);
    expect(mockedApi.fetchWebappInfo).toHaveBeenCalledTimes(20);
  });

  it("keeps polling through transient fetch errors", async () => {
    mockedApi.fetchWebappInfo
      .mockRejectedValueOnce(new Error("sandbox not reachable"))
      .mockResolvedValue(webappInfo(true, true) as never);
    const pending = waitForWebappReady(SESSION_ID);
    await jest.advanceTimersByTimeAsync(30000);
    await pending;
    expect(mockedApi.fetchWebappInfo).toHaveBeenCalledTimes(2);
  });

  it("keeps polling while webapp existence is unknown", async () => {
    mockedApi.fetchWebappInfo
      .mockResolvedValueOnce(webappInfo(null, false) as never)
      .mockResolvedValue(webappInfo(false, false) as never);
    const pending = waitForWebappReady(SESSION_ID);
    await jest.advanceTimersByTimeAsync(30000);
    await pending;
    expect(mockedApi.fetchWebappInfo).toHaveBeenCalledTimes(2);
  });
});

describe("completed transcript handoff", () => {
  const user = {
    id: "user-db",
    type: "user" as const,
    content: "Build it",
    timestamp: new Date(),
    turn_index: 0,
  };
  const answer = {
    id: "answer-local",
    type: "assistant" as const,
    content: "Complete answer",
    message_metadata: {
      streamItems: [
        {
          type: "text",
          id: "answer-text",
          content: "Complete answer",
          isStreaming: false,
        },
      ],
    },
    timestamp: new Date(),
    turn_index: 0,
  };
  const receipt = {
    turnId: "completed-turn",
    turnGeneration: 0,
    phase: "ready" as const,
  };

  beforeEach(() => {
    jest.clearAllMocks();
    useBuildSessionStore.setState({
      sessions: new Map(),
      currentSessionId: null,
    });
    mockedApi.fetchSession.mockResolvedValue(runningSession() as never);
    mockedApi.fetchActiveTurn.mockResolvedValue(null);
    mockedApi.fetchMessages.mockResolvedValue([user, answer]);
    mockedApi.fetchArtifacts.mockResolvedValue([]);
    mockedApi.fetchOutputInventory.mockResolvedValue({
      files: [],
      complete: true,
    });
    useBuildSessionStore.getState().createSession(SESSION_ID, {
      status: "running",
      isLoaded: true,
      messages: [user, answer],
      activeTurnId: "completed-turn",
    });
  });

  it("holds the streamed response until the server turn completes", async () => {
    jest.useFakeTimers();
    try {
      mockedApi.fetchActiveTurn.mockResolvedValue({
        turn_id: "completed-turn",
        turn_index: 0,
      } as never);
      mockedApi.fetchMessages.mockResolvedValue([user]);
      const settling = useBuildSessionStore
        .getState()
        .beginTurnSettlement(SESSION_ID, "completed-turn", 0);
      await jest.advanceTimersByTimeAsync(0);
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)?.messages
      ).toEqual([user, answer]);
      expect(mockedApi.fetchMessages).not.toHaveBeenCalled();
      const persisted = {
        ...answer,
        id: "canonical-answer",
        content: "Saved answer",
        message_metadata: {
          streamItems: [
            {
              type: "text",
              id: "saved-text",
              content: "Saved answer",
              isStreaming: false,
            },
          ],
        },
      };
      mockedApi.fetchActiveTurn.mockResolvedValue(null);
      mockedApi.fetchMessages.mockResolvedValue([user, persisted]);
      await jest.advanceTimersByTimeAsync(1000);
      await settling;
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)
      ).toMatchObject({
        messages: [user, persisted],
        status: "active",
        turnSettlement: receipt,
      });
    } finally {
      jest.useRealTimers();
    }
  });

  it("settles without waiting for runtime restoration", async () => {
    mockedApi.fetchSession.mockResolvedValue(sleepingSession() as never);
    await useBuildSessionStore
      .getState()
      .beginTurnSettlement(SESSION_ID, "completed-turn", 0);
    expect(mockedApi.fetchSession).not.toHaveBeenCalled();
    expect(mockedApi.restoreSession).not.toHaveBeenCalled();
    expect(
      useBuildSessionStore.getState().sessions.get(SESSION_ID)?.turnSettlement
    ).toEqual(receipt);
  });

  it("does not replace a newer turn during completion polling", async () => {
    jest.useFakeTimers();
    try {
      mockedApi.fetchActiveTurn.mockResolvedValue({
        turn_id: "completed-turn",
        turn_index: 0,
      } as never);
      const settling = useBuildSessionStore
        .getState()
        .beginTurnSettlement(SESSION_ID, "completed-turn", 0);
      await jest.advanceTimersByTimeAsync(0);
      useBuildSessionStore.getState().updateSessionData(SESSION_ID, {
        turnGeneration: 1,
        status: "running",
        activeTurnId: "newer-turn",
        turnSettlement: null,
      });
      const current = useBuildSessionStore.getState().sessions.get(SESSION_ID);
      await jest.advanceTimersByTimeAsync(1000);
      await settling;
      expect(useBuildSessionStore.getState().sessions.get(SESSION_ID)).toBe(
        current
      );
      expect(mockedApi.fetchMessages).not.toHaveBeenCalled();
    } finally {
      jest.useRealTimers();
    }
  });

  it("uses the canonical transcript after completion even when its text differs", async () => {
    useBuildSessionStore.getState().updateSessionData(SESSION_ID, {
      streamItems: [
        {
          type: "text",
          id: "live-answer",
          content: "Complete answer",
          isStreaming: false,
        },
      ],
    });
    const persisted = {
      ...answer,
      id: "answer-db",
      content: "Canonical answer",
      message_metadata: {
        streamItems: [
          {
            type: "text",
            id: "canonical-text",
            content: "Canonical answer",
            isStreaming: false,
          },
        ],
      },
    };
    mockedApi.fetchMessages.mockResolvedValue([user, persisted]);
    await useBuildSessionStore
      .getState()
      .beginTurnSettlement(SESSION_ID, "completed-turn", 0);
    expect(
      useBuildSessionStore.getState().sessions.get(SESSION_ID)
    ).toMatchObject({
      messages: [user, persisted],
      streamItems: [],
      turnSettlement: receipt,
    });
    expect(mockedApi.fetchActiveTurn.mock.invocationCallOrder[0]).toBeLessThan(
      mockedApi.fetchMessages.mock.invocationCallOrder[0] ?? Infinity
    );
  });

  it("retains the response on a completion lookup failure and allows retry", async () => {
    mockedApi.fetchActiveTurn.mockRejectedValueOnce(
      new Error("turn endpoint unavailable")
    );
    await useBuildSessionStore
      .getState()
      .beginTurnSettlement(SESSION_ID, "completed-turn", 0);
    expect(
      useBuildSessionStore.getState().sessions.get(SESSION_ID)
    ).toMatchObject({
      messages: [user, answer],
      turnSettlement: { phase: "failed", error: "turn endpoint unavailable" },
    });
    await useBuildSessionStore.getState().retryTurnSettlement(SESSION_ID);
    expect(
      useBuildSessionStore.getState().sessions.get(SESSION_ID)?.turnSettlement
    ).toEqual(receipt);
  });

  it("does not release held completion through a forced history load", async () => {
    const settlement = {
      ...receipt,
      phase: "failed" as const,
      error: "history unavailable",
    };
    useBuildSessionStore.getState().updateSessionData(SESSION_ID, {
      status: "idle",
      activeTurnId: null,
      turnSettlement: settlement,
    });
    mockedApi.fetchMessages.mockResolvedValue([user]);
    await useBuildSessionStore
      .getState()
      .loadSession(SESSION_ID, { force: true });
    expect(
      useBuildSessionStore.getState().sessions.get(SESSION_ID)
    ).toMatchObject({ messages: [user, answer], turnSettlement: settlement });
  });

  it("preserves completion learned after a history load started", async () => {
    const messages = deferred<Awaited<ReturnType<typeof api.fetchMessages>>>();
    mockedApi.fetchMessages.mockReturnValueOnce(messages.promise);
    const loading = useBuildSessionStore
      .getState()
      .loadSession(SESSION_ID, { force: true });
    await waitFor(() =>
      expect(mockedApi.fetchMessages).toHaveBeenCalledTimes(1)
    );
    await useBuildSessionStore
      .getState()
      .beginTurnSettlement(SESSION_ID, "completed-turn", 0);
    messages.resolve([user]);
    await loading;
    expect(
      useBuildSessionStore.getState().sessions.get(SESSION_ID)
    ).toMatchObject({ messages: [user, answer], turnSettlement: receipt });
  });

  it("keeps a newer live turn's identity when completion lookup fails", async () => {
    useBuildSessionStore.getState().updateSessionData(SESSION_ID, {
      activeTurnId: "next-turn",
      activeTurnIndex: 1,
      activeTurnLocalOwner: true,
    });
    mockedApi.fetchActiveTurn.mockRejectedValue(
      new Error("turn endpoint unavailable")
    );
    mockedApi.fetchMessages.mockResolvedValue([user]);
    await useBuildSessionStore
      .getState()
      .loadSession(SESSION_ID, { force: true });
    expect(
      useBuildSessionStore.getState().sessions.get(SESSION_ID)
    ).toMatchObject({
      messages: [user, answer],
      status: "running",
      activeTurnId: "next-turn",
      activeTurnIndex: 1,
      activeTurnLocalOwner: true,
    });
  });

  it("rejects a history response from an older turn", async () => {
    const messages = deferred<Awaited<ReturnType<typeof api.fetchMessages>>>();
    mockedApi.fetchMessages.mockReturnValueOnce(messages.promise);
    const loading = useBuildSessionStore
      .getState()
      .loadSession(SESSION_ID, { force: true });
    await waitFor(() => expect(mockedApi.fetchMessages).toHaveBeenCalled());
    useBuildSessionStore.getState().updateSessionData(SESSION_ID, {
      turnGeneration: 1,
      status: "running",
      activeTurnId: "next-turn",
    });
    messages.resolve([user]);
    await loading;
    expect(
      useBuildSessionStore.getState().sessions.get(SESSION_ID)
    ).toMatchObject({
      messages: [user, answer],
      status: "running",
      activeTurnId: "next-turn",
    });
  });
});
