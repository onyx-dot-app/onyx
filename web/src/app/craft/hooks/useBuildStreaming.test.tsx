import { act, renderHook } from "@testing-library/react";

import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import { useBuildStreaming } from "@/app/craft/hooks/useBuildStreaming";
import type { StreamItem } from "@/app/craft/types/displayTypes";
import type { OutputFile } from "@/app/craft/types/streamingTypes";
import {
  createTurn,
  fetchActiveTurn,
  fetchArtifacts,
  fetchOutputInventory,
  fetchScheduledRunEventStream,
  fetchScheduledRunContext,
  fetchMessages,
  fetchSession,
  fetchWebappInfo,
  fetchTurnEventStream,
  interruptMessageStream,
  processSSEStream,
  RateLimitedError,
} from "@/app/craft/services/apiServices";

jest.mock("swr", () => ({
  useSWRConfig: () => ({ mutate: jest.fn() }),
}));

jest.mock("@/app/craft/services/apiServices", () => ({
  RateLimitedError: class RateLimitedError extends Error {
    details: Record<string, unknown>;
    constructor(message: string, details: Record<string, unknown>) {
      super(message);
      this.details = details;
    }
  },
  createTurn: jest.fn(),
  fetchActiveTurn: jest.fn(),
  fetchArtifacts: jest.fn(),
  fetchOutputInventory: jest.fn(),
  fetchMessages: jest.fn(),
  fetchScheduledRunEventStream: jest.fn(),
  fetchScheduledRunContext: jest.fn(),
  fetchSession: jest.fn(),
  fetchWebappInfo: jest.fn(),
  fetchTurnEventStream: jest.fn(),
  interruptMessageStream: jest.fn(),
  processSSEStream: jest.fn(),
}));

const sessionId = "session-thinking";
const originalLoadSession = useBuildSessionStore.getState().loadSession;

describe("useBuildStreaming thinking packets", () => {
  beforeEach(() => {
    jest.useFakeTimers();
    jest.clearAllMocks();
    useBuildSessionStore.setState({
      currentSessionId: null,
      sessions: new Map(),
      loadSession: jest.fn().mockResolvedValue(undefined),
    } as never);
    useBuildSessionStore.getState().createSession(sessionId, {
      status: "active",
      isLoaded: true,
      outputInventory: {},
    });

    jest
      .mocked(fetchOutputInventory)
      .mockResolvedValue({ files: [], complete: true });
    jest.mocked(fetchWebappInfo).mockResolvedValue({
      has_webapp: false,
      webapp_url: null,
      ready: false,
      status: "running",
      sharing_scope: "private",
    });

    jest.mocked(fetchActiveTurn).mockResolvedValue(null);
    jest.mocked(fetchScheduledRunContext).mockResolvedValue({
      run_id: "scheduled-run",
      task_id: "task",
      task_name: "Task",
      status: "SUCCEEDED",
      started_at: "2026-10-10T00:00:00Z",
      finished_at: null,
    });
    jest
      .mocked(fetchMessages)
      .mockImplementation(
        async (id) =>
          useBuildSessionStore.getState().sessions.get(id)?.messages ?? []
      );

    jest.mocked(createTurn).mockResolvedValue({
      session_id: sessionId,
      turn_id: "turn-thinking",
      status: "QUEUED",
      turn_index: 0,
    });
    jest.mocked(fetchTurnEventStream).mockResolvedValue({} as Response);
    jest.mocked(interruptMessageStream).mockResolvedValue();
    jest
      .mocked(processSSEStream)
      .mockImplementation(async (_response, onPacket) => {
        onPacket({
          sessionUpdate: "agent_thought_chunk",
          content: { type: "text", text: "Inspecting the app state." },
          timestamp: "2026-01-01T00:00:00Z",
        } as never);
        onPacket({
          type: "tool_call_start",
          tool_call_id: "tool-read",
          kind: "read",
          title: "Read file",
          content: null,
          locations: null,
          raw_input: null,
          raw_output: null,
          status: "pending",
          timestamp: "2026-01-01T00:00:01Z",
        } as never);
      });
  });

  afterEach(() => {
    act(() => {
      jest.runOnlyPendingTimers();
    });
    useBuildSessionStore.setState({
      loadSession: originalLoadSession,
    } as never);
    jest.useRealTimers();
  });

  it("settles a thought when the next packet arrives while keeping the row visible", async () => {
    jest
      .mocked(fetchActiveTurn)
      .mockResolvedValue({ turn_id: "turn-thinking", turn_index: 0 } as never);
    const emitPackets = jest.mocked(processSSEStream).getMockImplementation();
    if (!emitPackets) throw new Error("Missing packet fixture");
    jest.mocked(processSSEStream).mockImplementationOnce(async (...args) => {
      await emitPackets(...args);
      throw new DOMException("Subscription closed", "AbortError");
    });
    const { result } = renderHook(() => useBuildStreaming());

    await act(async () => {
      await result.current.streamMessage(sessionId, "build the app");
    });

    const streamItems =
      useBuildSessionStore.getState().sessions.get(sessionId)?.streamItems ??
      [];

    expect(streamItems).toHaveLength(2);
    expect(streamItems[0]).toMatchObject({
      type: "thinking",
      content: "Inspecting the app state.",
      isStreaming: false,
    });
    expect(streamItems[1]).toMatchObject({
      type: "tool_call",
      id: "tool-read",
    });
  });

  it.each([
    { changesDuringTurn: false, expected: false },
    { changesDuringTurn: true, expected: true },
  ])(
    "reconciles stale skills after turn creation when changesDuringTurn is $changesDuringTurn",
    async ({ changesDuringTurn, expected }) => {
      let resolveTurn: (
        turn: Awaited<ReturnType<typeof createTurn>>
      ) => void = () => {};
      jest.mocked(createTurn).mockReturnValueOnce(
        new Promise((resolve) => {
          resolveTurn = resolve;
        })
      );
      useBuildSessionStore.getState().updateSessionData(sessionId, {
        skillsStale: true,
      });
      const { result } = renderHook(() => useBuildStreaming());

      const stream = result.current.streamMessage(sessionId, "build the app");
      if (changesDuringTurn) {
        useBuildSessionStore.getState().updateSessionData(sessionId, {
          skillsStale: true,
        });
      }
      resolveTurn({
        session_id: sessionId,
        turn_id: "turn-thinking",
        status: "QUEUED",
        turn_index: 0,
      });
      await act(async () => stream);

      expect(
        useBuildSessionStore.getState().sessions.get(sessionId)?.skillsStale
      ).toBe(expected);
    }
  );

  it("does not reset the abort controller when a newer turn took ownership mid-stream", async () => {
    const newerController = new AbortController();
    jest.mocked(processSSEStream).mockImplementationOnce(async () => {
      // Simulate a queued message auto-sending mid-stream: the newer turn
      // installs its own controller while this one is still settling.
      useBuildSessionStore
        .getState()
        .setAbortController(sessionId, newerController);
    });
    const { result } = renderHook(() => useBuildStreaming());

    await act(async () => {
      await result.current.streamMessage(sessionId, "hello");
    });

    // The completed turn's finally must not clobber the newer turn's controller,
    // or the newer turn's streamTurnEvents trips the duplicate-watcher guard.
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)?.abortController
    ).toBe(newerController);
  });

  it("refreshes files only when an output write completes", async () => {
    useBuildSessionStore.getState().updateFilesTabState(sessionId, {
      expandedPaths: ["attachments", "attachments/reports"],
    });
    jest
      .mocked(processSSEStream)
      .mockImplementationOnce(async (_response, onPacket) => {
        for (const status of ["pending", "in_progress", "completed"] as const) {
          onPacket({
            type: "tool_call_progress",
            tool_call_id: "write-output",
            kind: "edit",
            status,
            raw_input: { filePath: "outputs/report.txt" },
            raw_output: null,
            _meta: { toolName: "write" },
          } as never);
        }
      });

    const { result } = renderHook(() => useBuildStreaming());

    await act(async () => {
      await result.current.streamMessage(sessionId, "write a report");
    });

    const session = useBuildSessionStore.getState().sessions.get(sessionId);
    expect(session?.filesNeedsRefresh).toBe(1);
    expect(session?.webappNeedsRefresh).toBe(0);
    expect(session?.filesTabState.expandedPaths).toEqual([
      "attachments",
      "attachments/reports",
    ]);
  });

  it("refreshes both files and preview for a completed output web write", async () => {
    jest
      .mocked(processSSEStream)
      .mockImplementationOnce(async (_response, onPacket) => {
        onPacket({
          type: "tool_call_progress",
          tool_call_id: "write-web-output",
          kind: "edit",
          status: "completed",
          raw_input: {
            filePath:
              "/workspace/sessions/323d7ce1-ea1b-42a8-bc34-ca5d8b4d27a3/outputs/web/app/page.tsx",
          },
          raw_output: null,
          _meta: { toolName: "write" },
        } as never);
      });

    const { result } = renderHook(() => useBuildStreaming());

    await act(async () => {
      await result.current.streamMessage(sessionId, "update the web app");
    });

    const session = useBuildSessionStore.getState().sessions.get(sessionId);
    expect(session?.filesNeedsRefresh).toBe(1);
    expect(session?.webappNeedsRefresh).toBe(1);
  });

  it("reconciles files when a turn completes", async () => {
    jest
      .mocked(processSSEStream)
      .mockImplementationOnce(async (_response, onPacket) => {
        onPacket({
          type: "tool_call_progress",
          tool_call_id: "mkdir-output",
          kind: "execute",
          status: "completed",
          raw_input: { command: "mkdir -p outputs/report" },
          raw_output: null,
          _meta: { toolName: "bash" },
        } as never);
        onPacket({ type: "prompt_response" } as never);
      });

    const { result } = renderHook(() => useBuildStreaming());

    await act(async () => {
      await result.current.streamMessage(
        sessionId,
        "create a report directory"
      );
    });

    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)?.filesNeedsRefresh
    ).toBe(1);
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)?.outputPanelOpen
    ).toBe(false);
  });

  function completeOutputTurn() {
    jest
      .mocked(processSSEStream)
      .mockImplementationOnce(async (_response, onPacket) => {
        onPacket({
          type: "tool_call_progress",
          tool_call_id: "generate-slides",
          kind: "execute",
          status: "completed",
          raw_input: { command: "python make_slides.py" },
          _meta: { toolName: "bash" },
        } as never);
        onPacket({ type: "prompt_response" } as never);
      });
  }

  it("discovers nested script outputs in one inventory and selects a PowerPoint in an open panel", async () => {
    useBuildSessionStore.getState().updateSessionData(sessionId, {
      outputPanelOpen: true,
      activeOutputTab: "files",
    });
    // GET /outputs returns a flat inventory, including nested files.
    jest.mocked(fetchOutputInventory).mockResolvedValue({
      complete: true,
      files: [
        { path: "outputs/notes.md", revision: "1:10", size: 100 },
        { path: "outputs/slides/deck.PPTX", revision: "2:100", size: 100 },
      ],
    });
    completeOutputTurn();
    const { result } = renderHook(() => useBuildStreaming());
    await act(async () => {
      await result.current.streamMessage(sessionId, "make slides");
    });
    const session = useBuildSessionStore.getState().sessions.get(sessionId);
    expect(session).toMatchObject({
      outputPanelOpen: true,
      activePanelTabId: "file:outputs/slides/deck.PPTX",
    });
    expect(session?.panelTabs).toHaveLength(2);
    expect(fetchOutputInventory).toHaveBeenCalledTimes(2);
  });

  it("sends and settles a prompt while the initial inventory is still loading", async () => {
    const store = () => useBuildSessionStore.getState();
    store().updateSessionData(sessionId, {
      outputInventory: null,
      outputBaselinePending: true,
    });
    let finishInitial:
      | ((inventory: Awaited<ReturnType<typeof fetchOutputInventory>>) => void)
      | undefined;
    jest.mocked(fetchOutputInventory).mockReturnValueOnce(
      new Promise((resolve) => {
        finishInitial = resolve;
      })
    );
    jest.mocked(fetchOutputInventory).mockResolvedValue({
      files: [{ path: "outputs/first.pdf", revision: "1", size: 100 }],
      complete: true,
    });
    const initial = store().refreshOutputInventory(sessionId, { silent: true });
    completeOutputTurn();
    const { result } = renderHook(() => useBuildStreaming());
    await act(async () => {
      await result.current.streamMessage(sessionId, "make a PDF");
    });
    expect(createTurn).toHaveBeenCalledTimes(1);
    expect(store().sessions.get(sessionId)).toMatchObject({
      status: "active",
      outputInventory: null,
    });
    await act(async () => {
      finishInitial?.({ files: [], complete: true });
      await initial;
    });
    expect(store().sessions.get(sessionId)).toMatchObject({
      outputInventory: {
        "outputs/first.pdf": {
          path: "outputs/first.pdf",
          revision: "1",
          size: 100,
        },
      },
      outputPanelOpen: false,
      outputBaselinePending: false,
    });
  });

  it("settles a turn before slow final discovery and retries a temporary failure", async () => {
    let failRead: ((error: Error) => void) | undefined;
    jest.mocked(fetchOutputInventory).mockReturnValueOnce(
      new Promise((_resolve, reject) => {
        failRead = reject;
      })
    );
    jest.mocked(fetchOutputInventory).mockResolvedValue({
      files: [{ path: "outputs/new.pdf", revision: "1", size: 100 }],
      complete: true,
    });
    completeOutputTurn();
    const { result } = renderHook(() => useBuildStreaming());
    await act(async () => {
      await result.current.streamMessage(sessionId, "make a PDF");
    });
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)?.status
    ).toBe("active");
    await act(async () => {
      await jest.advanceTimersByTimeAsync(3000);
    });
    expect(fetchOutputInventory).toHaveBeenCalledTimes(1);
    expect(jest.mocked(fetchOutputInventory).mock.calls[0]?.[1]?.aborted).toBe(
      false
    );
    await act(async () => {
      failRead?.(new Error("sandbox unavailable"));
      await jest.advanceTimersByTimeAsync(1000);
    });
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)?.activePanelTabId
    ).toBe("file:outputs/new.pdf");
  });

  it("bounds pending tool reads and queues final discovery before focus", async () => {
    const deck: OutputFile = {
      path: "outputs/deck.pptx",
      revision: "1",
      size: 100,
    };
    let finishToolRead:
      | ((inventory: Awaited<ReturnType<typeof fetchOutputInventory>>) => void)
      | undefined;
    jest
      .mocked(fetchOutputInventory)
      .mockReturnValueOnce(
        new Promise((resolve) => {
          finishToolRead = resolve;
        })
      )
      .mockResolvedValue({ files: [deck], complete: true });
    jest
      .mocked(processSSEStream)
      .mockImplementationOnce(async (_response, onPacket) => {
        onPacket({
          type: "tool_call_progress",
          tool_call_id: "prepare-slides",
          kind: "execute",
          status: "completed",
          _meta: { toolName: "bash" },
        } as never);
        await jest.advanceTimersByTimeAsync(400);
        expect(fetchOutputInventory).toHaveBeenCalledTimes(1);
        for (let index = 0; index < 3; index++) {
          onPacket({
            type: "tool_call_progress",
            tool_call_id: `prepare-slide-${index}`,
            kind: "execute",
            status: "completed",
            _meta: { toolName: "bash" },
          } as never);
          await jest.advanceTimersByTimeAsync(400);
        }
        onPacket({ type: "prompt_response" } as never);
        const focus = useBuildSessionStore
          .getState()
          .refreshOutputInventory(sessionId, { silent: true });
        // The older read saw no file; final discovery must run before focus.
        finishToolRead?.({ files: [], complete: true });
        await focus;
      });
    const { result } = renderHook(() => useBuildStreaming());
    await act(async () => {
      await result.current.streamMessage(sessionId, "make slides");
    });
    // Tool discovery, terminal discovery, focus, and canonical completion; no tool backlog.
    expect(fetchOutputInventory).toHaveBeenCalledTimes(4);
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)
    ).toMatchObject({
      outputPanelOpen: true,
      activePanelTabId: `file:${deck.path}`,
    });
  });

  it("coalesces tool completions and reveals outputs before the turn ends", async () => {
    jest.mocked(fetchOutputInventory).mockResolvedValue({
      complete: true,
      files: [{ path: "outputs/deck.pptx", revision: "1", size: 100 }],
    });
    jest
      .mocked(processSSEStream)
      .mockImplementationOnce(async (_response, onPacket) => {
        for (const id of ["write-slides", "render-slides"]) {
          onPacket({
            type: "tool_call_progress",
            tool_call_id: id,
            kind: "execute",
            status: "completed",
            raw_input: { command: "python make_slides.py" },
            _meta: { toolName: "bash" },
          } as never);
        }
        expect(fetchOutputInventory).toHaveBeenCalledTimes(0);
        await jest.advanceTimersByTimeAsync(400);
        expect(fetchOutputInventory).toHaveBeenCalledTimes(1);
        expect(
          useBuildSessionStore.getState().sessions.get(sessionId)
        ).toMatchObject({
          status: "running",
          outputPanelOpen: true,
          activePanelTabId: "file:outputs/deck.pptx",
        });
        onPacket({ type: "prompt_response" } as never);
      });
    const { result } = renderHook(() => useBuildStreaming());
    await act(async () => {
      await result.current.streamMessage(sessionId, "make slides");
    });
    expect(fetchOutputInventory).toHaveBeenCalledTimes(3);
  });

  it("combines tool completions during an inventory request into one follow-up", async () => {
    let finishInventory: (
      inventory: Awaited<ReturnType<typeof fetchOutputInventory>>
    ) => void = () => {};
    jest
      .mocked(fetchOutputInventory)
      .mockReturnValueOnce(
        new Promise((resolve) => {
          finishInventory = resolve;
        })
      )
      .mockResolvedValue({
        complete: true,
        files: [{ path: "outputs/deck.pptx", revision: "1", size: 100 }],
      });
    jest
      .mocked(processSSEStream)
      .mockImplementationOnce(async (_response, onPacket) => {
        const completeTool = (id: string) =>
          onPacket({
            type: "tool_call_progress",
            tool_call_id: id,
            kind: "execute",
            status: "completed",
            _meta: { toolName: "bash" },
          } as never);
        completeTool("write-slides");
        await jest.advanceTimersByTimeAsync(400);
        expect(fetchOutputInventory).toHaveBeenCalledTimes(1);
        completeTool("render-slides");
        completeTool("export-slides");
        await jest.advanceTimersByTimeAsync(400);
        expect(fetchOutputInventory).toHaveBeenCalledTimes(1);

        finishInventory({ files: [], complete: true });
        await jest.advanceTimersByTimeAsync(0);
        expect(fetchOutputInventory).toHaveBeenCalledTimes(2);
        expect(
          useBuildSessionStore.getState().sessions.get(sessionId)
            ?.activePanelTabId
        ).toBe("file:outputs/deck.pptx");
        onPacket({ type: "prompt_response" } as never);
      });
    const { result } = renderHook(() => useBuildStreaming());
    await act(async () => {
      await result.current.streamMessage(sessionId, "make slides");
    });
    expect(fetchOutputInventory).toHaveBeenCalledTimes(4);
  });

  it("cancels a pending inventory refresh when its stream is aborted", async () => {
    jest
      .mocked(processSSEStream)
      .mockImplementationOnce(async (_response, onPacket) => {
        onPacket({
          type: "tool_call_progress",
          tool_call_id: "write-slides",
          kind: "execute",
          status: "completed",
          _meta: { toolName: "bash" },
        } as never);
        throw new DOMException("Stream aborted", "AbortError");
      });
    const { result } = renderHook(() => useBuildStreaming());
    await act(async () => {
      await result.current.streamMessage(sessionId, "make slides");
      await jest.advanceTimersByTimeAsync(400);
    });
    expect(fetchOutputInventory).toHaveBeenCalledTimes(0);
  });

  it.each(["manual", "automatic"] as const)(
    "resets a %s selection lock for the next task",
    async (selection) => {
      jest.mocked(fetchOutputInventory).mockResolvedValue({
        complete: true,
        files: [{ path: "outputs/deck.pptx", revision: "1", size: 100 }],
      });
      jest
        .mocked(processSSEStream)
        .mockImplementationOnce(async (_response, onPacket) => {
          if (selection === "manual")
            useBuildSessionStore
              .getState()
              .setActiveOutputTab(sessionId, "files");
          onPacket({
            type: "tool_call_progress",
            tool_call_id: "write",
            kind: "execute",
            status: "completed",
            raw_input: { command: "python make_slides.py" },
            _meta: { toolName: "bash" },
          } as never);
          onPacket({ type: "prompt_response" } as never);
        });
      const { result } = renderHook(() => useBuildStreaming());
      await act(async () => {
        await result.current.streamMessage(sessionId, "make slides");
      });
      expect(
        useBuildSessionStore.getState().sessions.get(sessionId)
      ).toMatchObject({
        activePanelTabId:
          selection === "manual" ? null : "file:outputs/deck.pptx",
        outputSelectionLocked: true,
      });
      jest.mocked(fetchOutputInventory).mockResolvedValue({
        complete: true,
        files: [
          { path: "outputs/deck.pptx", revision: "1", size: 100 },
          { path: "outputs/second.pdf", revision: "2", size: 100 },
        ],
      });
      completeOutputTurn();
      await act(async () => {
        await result.current.streamMessage(sessionId, "make a PDF too");
      });
      expect(
        useBuildSessionStore.getState().sessions.get(sessionId)
          ?.activePanelTabId
      ).toBe("file:outputs/second.pdf");
    }
  );

  it("preserves a manual output choice when reattaching to a scheduled run", async () => {
    useBuildSessionStore.getState().setActiveOutputTab(sessionId, "files");
    jest.mocked(fetchScheduledRunEventStream).mockResolvedValue({} as Response);
    jest.mocked(fetchOutputInventory).mockResolvedValue({
      complete: true,
      files: [{ path: "outputs/scheduled.pptx", revision: "1", size: 100 }],
    });
    completeOutputTurn();
    const { result } = renderHook(() => useBuildStreaming());
    await act(async () => {
      await result.current.streamScheduledRunEvents(
        sessionId,
        "scheduled-run",
        new AbortController().signal
      );
    });
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)
    ).toMatchObject({
      activeOutputTab: "files",
      activePanelTabId: null,
      outputSelectionLocked: true,
      outputInventory: {
        "outputs/scheduled.pptx": {
          path: "outputs/scheduled.pptx",
          revision: "1",
          size: 100,
        },
      },
    });
  });

  it("keeps dismissal for this task and lets the next task open its new output", async () => {
    const store = () => useBuildSessionStore.getState();
    store().setCurrentSession(sessionId);
    jest.mocked(fetchOutputInventory).mockResolvedValue({
      complete: true,
      files: [{ path: "outputs/deck.pptx", revision: "1", size: 100 }],
    });
    jest
      .mocked(processSSEStream)
      .mockImplementationOnce(async (_response, onPacket) => {
        store().toggleCurrentOutputPanel();
        store().toggleCurrentOutputPanel();
        onPacket({ type: "prompt_response" } as never);
      });
    const { result } = renderHook(() => useBuildStreaming());
    await act(async () => {
      await result.current.streamMessage(sessionId, "make slides");
    });
    expect(store().sessions.get(sessionId)).toMatchObject({
      outputPanelOpen: false,
      activePanelTabId: null,
    });

    jest.mocked(fetchOutputInventory).mockResolvedValue({
      complete: true,
      files: [
        { path: "outputs/deck.pptx", revision: "1", size: 100 },
        { path: "outputs/report.pdf", revision: "2", size: 100 },
      ],
    });
    completeOutputTurn();
    await act(async () => {
      await result.current.streamMessage(sessionId, "make a report");
    });
    expect(store().sessions.get(sessionId)).toMatchObject({
      outputPanelOpen: true,
      activePanelTabId: "file:outputs/report.pdf",
    });
  });

  it.each(["terminal", "end-of-stream", "already-settled"] as const)(
    "discovers outputs after missed tool events with %s settlement",
    async (settlement) => {
      jest.mocked(fetchOutputInventory).mockResolvedValue({
        complete: true,
        files: [{ path: "outputs/missed.pptx", revision: "1", size: 100 }],
      });
      if (settlement === "already-settled") {
        jest.mocked(fetchTurnEventStream).mockResolvedValueOnce(null);
      } else {
        jest
          .mocked(processSSEStream)
          .mockImplementationOnce(async (_response, onPacket) => {
            if (settlement === "terminal") {
              onPacket({ type: "prompt_response" } as never);
            }
          });
      }
      const { result } = renderHook(() => useBuildStreaming());
      await act(async () => {
        await result.current.streamTurnEvents(
          sessionId,
          "turn-late-attach",
          new AbortController().signal
        );
      });
      expect(
        useBuildSessionStore.getState().sessions.get(sessionId)
      ).toMatchObject({
        outputPanelOpen: true,
        activePanelTabId: "file:outputs/missed.pptx",
      });
      expect(fetchOutputInventory).toHaveBeenCalledTimes(2);
    }
  );

  it("does not refresh unchanged files after a text-only turn", async () => {
    jest
      .mocked(processSSEStream)
      .mockImplementationOnce(async (_response, onPacket) => {
        onPacket({ type: "text_chunk", text: "Done." } as never);
        onPacket({ type: "prompt_response" } as never);
      });

    const { result } = renderHook(() => useBuildStreaming());

    await act(async () => {
      await result.current.streamMessage(sessionId, "explain the project");
    });

    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)?.filesNeedsRefresh
    ).toBe(0);
  });

  it("seeds clickable subagent metadata from a task start packet", async () => {
    jest
      .mocked(fetchActiveTurn)
      .mockResolvedValue({ turn_id: "turn-thinking", turn_index: 0 } as never);
    jest
      .mocked(processSSEStream)
      .mockImplementationOnce(async (_response, onPacket) => {
        onPacket({
          type: "tool_call_start",
          tool_call_id: "task-call-1",
          kind: "other",
          title: "Task",
          raw_input: {
            prompt: "Inspect the repository",
            subagent_type: "explore",
          },
          raw_output: null,
          status: "pending",
          _meta: {
            toolName: "task",
            subagentSessionId: "child-session-1",
          },
        } as never);
        throw new DOMException("Subscription closed", "AbortError");
      });

    const { result } = renderHook(() => useBuildStreaming());

    await act(async () => {
      await result.current.streamMessage(sessionId, "build the app");
    });

    const session = useBuildSessionStore.getState().sessions.get(sessionId);
    expect(session?.subagents.get("child-session-1")).toMatchObject({
      sessionId: "child-session-1",
      parentToolCallId: "task-call-1",
      name: "Inspect the repository",
      status: "running",
      turns: [expect.objectContaining({ prompt: "Inspect the repository" })],
    });
    expect(session?.streamItems).toEqual([
      expect.objectContaining({
        type: "tool_call",
        id: "task-call-1",
        toolCall: expect.objectContaining({
          command: "Inspect the repository",
          description: "Spawning subagent: Inspect the repository",
        }),
      }),
    ]);
  });

  it("links a visible running task row from a subagent_started packet", async () => {
    jest
      .mocked(fetchActiveTurn)
      .mockResolvedValue({ turn_id: "turn-thinking", turn_index: 0 } as never);
    jest
      .mocked(processSSEStream)
      .mockImplementationOnce(async (_response, onPacket) => {
        onPacket({
          type: "tool_call_start",
          tool_call_id: "task-call-1",
          kind: "task",
          title: "Task",
          raw_input: {
            prompt: "Build Space Invaders game",
          },
          raw_output: null,
          status: "pending",
          _meta: {
            toolName: "unknown",
          },
        } as never);
        onPacket({
          type: "tool_call_progress",
          tool_call_id: "task-call-1",
          kind: "task",
          status: "in_progress",
          raw_input: {
            prompt: "Build Space Invaders game",
            description: "Build Space Invaders game",
          },
          raw_output: null,
          _meta: {
            toolName: "task",
          },
        } as never);
        onPacket({
          type: "subagent_started",
          subagent_session_id: "child-session-1",
          parent_session_id: "parent-session-1",
        } as never);
        throw new DOMException("Subscription closed", "AbortError");
      });

    const { result } = renderHook(() => useBuildStreaming());

    await act(async () => {
      await result.current.streamMessage(sessionId, "build the app");
    });

    const session = useBuildSessionStore.getState().sessions.get(sessionId);
    expect(session?.subagents.get("child-session-1")).toMatchObject({
      sessionId: "child-session-1",
      parentToolCallId: "task-call-1",
      name: "Build Space Invaders game",
      status: "running",
      turns: [expect.objectContaining({ prompt: "Build Space Invaders game" })],
    });
    expect(session?.streamItems).toEqual([
      expect.objectContaining({
        type: "tool_call",
        id: "task-call-1",
        toolCall: expect.objectContaining({
          status: "in_progress",
          description: "Spawning subagent: Build Space Invaders game",
        }),
      }),
    ]);
  });

  it("appends a connect card stream item from a connect_app_request packet", async () => {
    jest
      .mocked(fetchActiveTurn)
      .mockResolvedValue({ turn_id: "turn-thinking", turn_index: 0 } as never);
    jest
      .mocked(processSSEStream)
      .mockImplementationOnce(async (_response, onPacket) => {
        onPacket({
          type: "connect_app_request",
          request_id: "req-1",
          external_app_id: 17,
          reason: "to schedule events",
        } as never);
        throw new DOMException("Subscription closed", "AbortError");
      });

    const { result } = renderHook(() => useBuildStreaming());

    await act(async () => {
      await result.current.streamMessage(sessionId, "what's on my calendar?");
    });

    const session = useBuildSessionStore.getState().sessions.get(sessionId);
    expect(session?.streamItems).toEqual([
      expect.objectContaining({
        type: "connect_app_request",
        id: "req-1",
        requestId: "req-1",
        externalAppId: 17,
        reason: "to schedule events",
      }),
    ]);
  });

  it("replaces placeholder subagent metadata when task progress names the child", async () => {
    jest
      .mocked(fetchActiveTurn)
      .mockResolvedValue({ turn_id: "turn-thinking", turn_index: 0 } as never);
    jest
      .mocked(processSSEStream)
      .mockImplementationOnce(async (_response, onPacket) => {
        onPacket({
          type: "tool_call_start",
          tool_call_id: "task-call-1",
          kind: "other",
          title: "Running task",
          raw_input: null,
          raw_output: null,
          status: "pending",
          _meta: {
            toolName: "task",
          },
        } as never);
        onPacket({
          type: "subagent_started",
          subagent_session_id: "child-session-1",
          parent_session_id: "parent-session-1",
        } as never);
        onPacket({
          type: "tool_call_progress",
          tool_call_id: "task-call-1",
          kind: "other",
          status: "in_progress",
          raw_input: {
            description: "Live stream smoke subagent",
            prompt:
              "Say hello, inspect one small file if available, then report done.",
            subagent_type: "general",
          },
          raw_output: null,
          _meta: {
            toolName: "task",
          },
        } as never);
        throw new DOMException("Subscription closed", "AbortError");
      });

    const { result } = renderHook(() => useBuildStreaming());

    await act(async () => {
      await result.current.streamMessage(sessionId, "build the app");
    });

    const subagent = useBuildSessionStore
      .getState()
      .sessions.get(sessionId)
      ?.subagents.get("child-session-1");

    expect(subagent).toMatchObject({
      name: "Live stream smoke subagent",
      parentToolCallId: "task-call-1",
      subagentType: "general",
      turns: [
        expect.objectContaining({
          prompt:
            "Say hello, inspect one small file if available, then report done.",
        }),
      ],
    });
  });

  it("streams child text and thinking into the active subagent body", async () => {
    jest
      .mocked(fetchActiveTurn)
      .mockResolvedValue({ turn_id: "turn-thinking", turn_index: 0 } as never);
    jest
      .mocked(processSSEStream)
      .mockImplementationOnce(async (_response, onPacket) => {
        onPacket({
          type: "tool_call_start",
          tool_call_id: "task-call-1",
          kind: "task",
          title: "Task",
          raw_input: {
            prompt: "Build Space Invaders game",
          },
          raw_output: null,
          status: "pending",
          _meta: {
            toolName: "task",
          },
        } as never);
        onPacket({
          type: "subagent_started",
          subagent_session_id: "child-session-1",
          parent_session_id: "parent-session-1",
        } as never);
        onPacket({
          type: "agent_thought_chunk",
          content: { type: "text", text: "Inspecting files." },
          _meta: {
            sessionId: "child-session-1",
            parentSessionId: "parent-session-1",
          },
        } as never);
        onPacket({
          type: "agent_message_chunk",
          content: { type: "text", text: "Built the game." },
          _meta: {
            sessionId: "child-session-1",
            parentSessionId: "parent-session-1",
          },
        } as never);
        throw new DOMException("Subscription closed", "AbortError");
      });

    const { result } = renderHook(() => useBuildStreaming());

    await act(async () => {
      await result.current.streamMessage(sessionId, "build the app");
    });

    const subagent = useBuildSessionStore
      .getState()
      .sessions.get(sessionId)
      ?.subagents.get("child-session-1");

    expect(subagent?.turns[0]).toMatchObject({
      prompt: "Build Space Invaders game",
      thinking: "Inspecting files.",
      response: "Built the game.",
      streamItems: [
        expect.objectContaining({
          type: "thinking",
          content: "Inspecting files.",
          isStreaming: false,
        }),
        expect.objectContaining({
          type: "text",
          content: "Built the game.",
          isStreaming: true,
        }),
      ],
    });
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)?.streamItems
    ).toEqual([
      expect.objectContaining({
        type: "tool_call",
        id: "task-call-1",
      }),
    ]);
  });

  it("does not drop child chunks that arrive before task metadata", async () => {
    jest
      .mocked(fetchActiveTurn)
      .mockResolvedValue({ turn_id: "turn-thinking", turn_index: 0 } as never);
    jest
      .mocked(processSSEStream)
      .mockImplementationOnce(async (_response, onPacket) => {
        onPacket({
          type: "agent_message_chunk",
          content: { type: "text", text: "Early child output." },
          _meta: {
            sessionId: "child-session-early",
            parentSessionId: "parent-session-1",
          },
        } as never);
        throw new DOMException("Subscription closed", "AbortError");
      });

    const { result } = renderHook(() => useBuildStreaming());

    await act(async () => {
      await result.current.streamMessage(sessionId, "build the app");
    });

    const subagent = useBuildSessionStore
      .getState()
      .sessions.get(sessionId)
      ?.subagents.get("child-session-early");

    expect(subagent).toMatchObject({
      sessionId: "child-session-early",
      status: "running",
      turns: [
        expect.objectContaining({
          response: "Early child output.",
          streamItems: [
            expect.objectContaining({
              type: "text",
              content: "Early child output.",
              isStreaming: true,
            }),
          ],
        }),
      ],
    });
  });

  it("records child tool starts in the active subagent stream", async () => {
    jest
      .mocked(fetchActiveTurn)
      .mockResolvedValue({ turn_id: "turn-thinking", turn_index: 0 } as never);
    jest
      .mocked(processSSEStream)
      .mockImplementationOnce(async (_response, onPacket) => {
        onPacket({
          type: "tool_call_start",
          tool_call_id: "task-call-1",
          kind: "task",
          title: "Task",
          raw_input: {
            prompt: "Build Space Invaders game",
          },
          raw_output: null,
          status: "pending",
          _meta: {
            toolName: "task",
          },
        } as never);
        onPacket({
          type: "subagent_started",
          subagent_session_id: "child-session-1",
          parent_session_id: "parent-session-1",
        } as never);
        onPacket({
          type: "agent_thought_chunk",
          content: { type: "text", text: "Checking the app." },
          _meta: {
            sessionId: "child-session-1",
            parentSessionId: "parent-session-1",
          },
        } as never);
        onPacket({
          type: "agent_message_chunk",
          content: { type: "text", text: "First update." },
          _meta: {
            sessionId: "child-session-1",
            parentSessionId: "parent-session-1",
          },
        } as never);
        onPacket({
          type: "tool_call_start",
          tool_call_id: "child-read-1",
          kind: "read",
          status: "pending",
          raw_input: { file_path: "web/src/app/page.tsx" },
          raw_output: null,
          _meta: {
            toolName: "read",
            sessionId: "child-session-1",
            parentSessionId: "parent-session-1",
          },
        } as never);
        onPacket({
          type: "agent_message_chunk",
          content: { type: "text", text: "Done." },
          _meta: {
            sessionId: "child-session-1",
            parentSessionId: "parent-session-1",
          },
        } as never);
        throw new DOMException("Subscription closed", "AbortError");
      });

    const { result } = renderHook(() => useBuildStreaming());

    await act(async () => {
      await result.current.streamMessage(sessionId, "build the app");
    });

    const subagent = useBuildSessionStore
      .getState()
      .sessions.get(sessionId)
      ?.subagents.get("child-session-1");

    expect(subagent?.turns[0]).toMatchObject({
      prompt: "Build Space Invaders game",
      toolCalls: [
        expect.objectContaining({
          id: "child-read-1",
          status: "pending",
          description: "src/app/page.tsx",
        }),
      ],
      streamItems: [
        expect.objectContaining({
          type: "thinking",
          content: "Checking the app.",
          isStreaming: false,
        }),
        expect.objectContaining({
          type: "text",
          content: "First update.",
          isStreaming: false,
        }),
        expect.objectContaining({
          type: "tool_call",
          id: "child-read-1",
        }),
        expect.objectContaining({
          type: "text",
          content: "Done.",
          isStreaming: true,
        }),
      ],
    });
  });

  it("links child subagent events to an active task row while streaming", async () => {
    jest
      .mocked(fetchActiveTurn)
      .mockResolvedValue({ turn_id: "turn-thinking", turn_index: 0 } as never);
    jest
      .mocked(processSSEStream)
      .mockImplementationOnce(async (_response, onPacket) => {
        onPacket({
          type: "tool_call_start",
          tool_call_id: "task-call-1",
          kind: "task",
          title: "Task",
          raw_input: {
            prompt: "Build Space Invaders game",
          },
          raw_output: null,
          status: "pending",
          _meta: {
            toolName: "unknown",
          },
        } as never);
        onPacket({
          type: "tool_call_progress",
          tool_call_id: "child-read-1",
          kind: "read",
          status: "completed",
          raw_input: { file_path: "web/src/app/page.tsx" },
          raw_output: { output: "page contents" },
          _meta: {
            toolName: "read",
            sessionId: "child-session-1",
            parentSessionId: "parent-session-1",
          },
        } as never);
        throw new DOMException("Subscription closed", "AbortError");
      });

    const { result } = renderHook(() => useBuildStreaming());

    await act(async () => {
      await result.current.streamMessage(sessionId, "build the app");
    });

    const session = useBuildSessionStore.getState().sessions.get(sessionId);
    expect(session?.subagents.get("child-session-1")).toMatchObject({
      sessionId: "child-session-1",
      parentToolCallId: "task-call-1",
      status: "running",
      turns: [
        expect.objectContaining({
          toolCalls: [
            expect.objectContaining({
              id: "child-read-1",
              status: "completed",
            }),
          ],
        }),
      ],
    });
  });

  it("saves thought stream items into assistant metadata on prompt_response", async () => {
    jest
      .mocked(processSSEStream)
      .mockImplementationOnce(async (_response, onPacket) => {
        onPacket({
          sessionUpdate: "agent_thought_chunk",
          content: { type: "text", text: "Inspecting the app state." },
          timestamp: "2026-01-01T00:00:00Z",
        } as never);
        onPacket({
          sessionUpdate: "agent_message_chunk",
          content: { type: "text", text: "Built the app." },
          timestamp: "2026-01-01T00:00:01Z",
        } as never);
        onPacket({
          type: "prompt_response",
          timestamp: "2026-01-01T00:00:02Z",
        });
      });

    const { result } = renderHook(() => useBuildStreaming());

    await act(async () => {
      await result.current.streamMessage(sessionId, "build the app");
    });

    const session = useBuildSessionStore.getState().sessions.get(sessionId);
    const assistantMessage = session?.messages.find(
      (message) => message.type === "assistant"
    );
    const metadata = assistantMessage?.message_metadata as
      | { streamItems?: StreamItem[] }
      | undefined;

    expect(session?.streamItems).toEqual([]);
    expect(assistantMessage?.content).toBe("Built the app.");
    expect(metadata?.streamItems).toEqual([
      expect.objectContaining({
        type: "thinking",
        content: "Inspecting the app state.",
        isStreaming: false,
      }),
      expect.objectContaining({
        type: "text",
        content: "Built the app.",
        isStreaming: false,
      }),
    ]);
  });

  it("hands attach transport failure to authoritative completion", async () => {
    jest
      .mocked(fetchTurnEventStream)
      .mockRejectedValueOnce(new Error("stream failed"));
    const { result } = renderHook(() => useBuildStreaming());

    await act(async () => {
      await result.current.streamTurnEvents(
        sessionId,
        "turn-failed",
        new AbortController().signal
      );
    });

    const session = useBuildSessionStore.getState().sessions.get(sessionId);
    expect(session).toMatchObject({
      status: "active",
      activeTurnId: null,
      turnSettlement: expect.objectContaining({ phase: "ready" }),
      activeTurnLocalOwner: false,
    });
    expect(useBuildSessionStore.getState().loadSession).not.toHaveBeenCalled();
  });

  it("shows in-band turn errors and clears active turn metadata", async () => {
    jest
      .mocked(processSSEStream)
      .mockImplementationOnce(async (_response, onPacket) => {
        onPacket({
          type: "error",
          message: "provider model not found",
        } as never);
      });
    const { result } = renderHook(() => useBuildStreaming());

    await act(async () => {
      await result.current.streamTurnEvents(
        sessionId,
        "turn-error",
        new AbortController().signal
      );
    });

    const session = useBuildSessionStore.getState().sessions.get(sessionId);
    expect(session).toMatchObject({
      status: "failed",
      error: "provider model not found",
      activeTurnId: null,
      activeTurnLocalOwner: false,
    });
    expect(session?.streamItems).toEqual([
      expect.objectContaining({
        type: "error",
        content: "provider model not found",
      }),
    ]);
  });

  it("surfaces a usage rate-limit 429 as an in-transcript banner item", async () => {
    jest.mocked(createTurn).mockRejectedValueOnce(
      new RateLimitedError("You've reached the usage budget.", {
        scope: "user",
        reset_at: "2026-01-02T00:00:00Z",
        retry_after_seconds: 3600,
      })
    );
    const { result } = renderHook(() => useBuildStreaming());

    await act(async () => {
      await result.current.streamMessage(sessionId, "build the app");
    });

    // Recoverable once the budget resets: session stays active (not failed),
    // but `error` stays set so queued messages don't auto-send into the limit.
    const session = useBuildSessionStore.getState().sessions.get(sessionId);
    expect(session).toMatchObject({
      status: "active",
      error: "You've reached the usage budget.",
      activeTurnId: null,
      activeTurnLocalOwner: false,
    });
    expect(session?.streamItems).toEqual([
      expect.objectContaining({
        type: "error",
        content: "You've reached the usage budget.",
        rateLimit: {
          scope: "user",
          reset_at: "2026-01-02T00:00:00Z",
          retry_after_seconds: 3600,
        },
      }),
    ]);
  });

  it("defers to reconcile when an error packet arrives mid-interrupt", async () => {
    jest
      .mocked(processSSEStream)
      .mockImplementationOnce(async (_response, onPacket) => {
        onPacket({ type: "error", message: "Aborted" } as never);
      });
    useBuildSessionStore.getState().updateSessionData(sessionId, {
      status: "running",
      activeTurnId: "turn-interrupted",
      activeTurnLocalOwner: false,
      isInterrupting: true,
    });
    const { result } = renderHook(() => useBuildStreaming());

    await act(async () => {
      await result.current.streamTurnEvents(
        sessionId,
        "turn-interrupted",
        new AbortController().signal
      );
    });

    // An error mid-interrupt (opencode's abort surfaces as one) must not mark the
    // session failed — that strands the queued auto-send. Settlement defers to
    // reconcile, so status/error/streamItems are left untouched.
    const session = useBuildSessionStore.getState().sessions.get(sessionId);
    expect(session?.status).toBe("running");
    expect(session?.error).toBeNull();
    expect(session?.isInterrupting).toBe(true);
    expect(session?.streamItems).toEqual([]);
  });

  it("clears stale turn metadata when the backend says the turn is not running", async () => {
    jest.mocked(fetchTurnEventStream).mockResolvedValueOnce(null);
    const { result } = renderHook(() => useBuildStreaming());

    await act(async () => {
      await result.current.streamTurnEvents(
        sessionId,
        "turn-stale",
        new AbortController().signal
      );
    });

    const session = useBuildSessionStore.getState().sessions.get(sessionId);
    expect(session).toMatchObject({
      status: "active",
      activeTurnId: null,
      activeTurnLocalOwner: false,
    });
    expect(fetchMessages).toHaveBeenCalledWith(sessionId);
  });

  it("defers settlement to reconcile when a stream settles mid-interrupt", async () => {
    jest.mocked(processSSEStream).mockResolvedValueOnce(undefined);
    useBuildSessionStore.getState().updateSessionData(sessionId, {
      status: "running",
      activeTurnId: "turn-interrupted-settled",
      activeTurnLocalOwner: false,
      isInterrupting: true,
    });
    const { result } = renderHook(() => useBuildStreaming());

    await act(async () => {
      await result.current.streamTurnEvents(
        sessionId,
        "turn-interrupted-settled",
        new AbortController().signal
      );
    });

    // Settlement is deferred to reconcile, so the stream end leaves state untouched.
    const session = useBuildSessionStore.getState().sessions.get(sessionId);
    expect(session).toMatchObject({
      status: "running",
      activeTurnId: "turn-interrupted-settled",
      isInterrupting: true,
    });
    expect(useBuildSessionStore.getState().loadSession).not.toHaveBeenCalled();
  });

  it("skips duplicate watchers for a locally owned turn", async () => {
    jest.mocked(fetchTurnEventStream).mockClear();
    const owner = new AbortController();
    useBuildSessionStore.getState().updateSessionData(sessionId, {
      activeTurnId: "turn-owned",
      activeTurnLocalOwner: true,
      abortController: owner,
    });
    const { result } = renderHook(() => useBuildStreaming());

    await act(async () => {
      await result.current.streamTurnEvents(
        sessionId,
        "turn-owned",
        new AbortController().signal
      );
    });

    expect(fetchTurnEventStream).not.toHaveBeenCalled();
  });

  it("loads an active turn from persisted packets and reattaches as one assistant turn", async () => {
    useBuildSessionStore.setState({
      loadSession: originalLoadSession,
    } as never);
    jest.mocked(fetchSession).mockResolvedValue({
      id: sessionId,
      status: "active",
      nextjs_port: null,
      session_loaded_in_sandbox: true,
      sandbox: { id: "sandbox-1", status: "running" },
      agent_provider: "openai",
      agent_model: "gpt-5-mini",
    } as never);
    jest
      .mocked(fetchActiveTurn)
      .mockResolvedValueOnce({
        session_id: sessionId,
        turn_id: "turn-reattach",
        status: "RUNNING",
        turn_index: 2,
      } as never)
      .mockResolvedValueOnce(null as never);
    jest.mocked(fetchArtifacts).mockResolvedValue([] as never);
    const userMessage = {
      id: "user-1",
      type: "user",
      content: "Build the app",
      timestamp: new Date("2026-01-01T00:00:00Z"),
      turn_index: 2,
      message_metadata: {
        type: "user_message",
        content: { type: "text", text: "Build the app" },
      },
    };
    const thoughtMessage = {
      id: "thought-1",
      type: "assistant",
      content: "",
      timestamp: new Date("2026-01-01T00:00:01Z"),
      turn_index: 2,
      message_metadata: {
        type: "agent_thought",
        content: { type: "text", text: "Inspecting files." },
      },
    };
    const partialAnswerMessage = {
      id: "answer-1",
      type: "assistant",
      content: "",
      timestamp: new Date("2026-01-01T00:00:02Z"),
      turn_index: 2,
      message_metadata: {
        type: "agent_message",
        content: { type: "text", text: "Partial" },
      },
    };
    const tailAnswerMessage = {
      ...partialAnswerMessage,
      id: "answer-2",
      timestamp: new Date("2026-01-01T00:00:03Z"),
      message_metadata: {
        type: "agent_message",
        content: { type: "text", text: " answer" },
      },
    };
    jest
      .mocked(fetchMessages)
      .mockResolvedValueOnce([
        userMessage,
        thoughtMessage,
        partialAnswerMessage,
      ] as never)
      .mockResolvedValueOnce([
        userMessage,
        thoughtMessage,
        partialAnswerMessage,
        tailAnswerMessage,
      ] as never);

    await act(async () => {
      await useBuildSessionStore
        .getState()
        .loadSession(sessionId, { force: true });
    });

    const restoredSession = useBuildSessionStore
      .getState()
      .sessions.get(sessionId);
    expect(restoredSession).toMatchObject({
      status: "running",
      activeTurnId: "turn-reattach",
      activeTurnIndex: 2,
    });
    expect(restoredSession?.messages).toEqual([
      expect.objectContaining({ id: "user-1", type: "user" }),
    ]);
    expect(restoredSession?.streamItems).toEqual([
      expect.objectContaining({
        type: "thinking",
        id: "thought-1",
        content: "Inspecting files.",
        isStreaming: false,
      }),
      expect.objectContaining({
        type: "text",
        id: "answer-1",
        content: "Partial",
        isStreaming: false,
      }),
    ]);

    jest
      .mocked(processSSEStream)
      .mockImplementationOnce(async (_response, onPacket) => {
        onPacket({
          sessionUpdate: "agent_message_chunk",
          content: { type: "text", text: " answer" },
          timestamp: "2026-01-01T00:00:01Z",
        } as never);
        onPacket({
          type: "prompt_response",
          timestamp: "2026-01-01T00:00:02Z",
        });
      });

    const { result } = renderHook(() => useBuildStreaming());

    await act(async () => {
      await result.current.streamTurnEvents(
        sessionId,
        "turn-reattach",
        new AbortController().signal
      );
    });

    const session = useBuildSessionStore.getState().sessions.get(sessionId);
    const assistantMessage = session?.messages.find(
      (message) => message.type === "assistant"
    );
    const assistantMessages =
      session?.messages.filter((message) => message.type === "assistant") ?? [];

    expect(session?.streamItems).toEqual([]);
    expect(assistantMessages).toHaveLength(1);
    expect(assistantMessage).toMatchObject({
      content: "Partial answer",
      turn_index: 2,
    });
  });

  it("marks the latest in-flight tool call as cancelled when interrupting", async () => {
    const { result } = renderHook(() => useBuildStreaming());

    act(() => {
      useBuildSessionStore.getState().updateSessionData(sessionId, {
        status: "running",
        activeTurnId: "tool-turn",
      });
      useBuildSessionStore.getState().appendStreamItem(sessionId, {
        type: "tool_call",
        id: "tool-finished",
        toolCall: {
          id: "tool-finished",
          kind: "read",
          toolName: "read",
          title: "Reading",
          description: "finished.ts",
          command: "",
          status: "completed",
          rawOutput: "",
        },
      });
      useBuildSessionStore.getState().appendStreamItem(sessionId, {
        type: "tool_call",
        id: "tool-active",
        toolCall: {
          id: "tool-active",
          kind: "execute",
          toolName: "bash",
          title: "Running command",
          description: "long-running command",
          command: "sleep 30",
          status: "in_progress",
          rawOutput: "",
        },
      });
    });

    await act(async () => {
      await result.current.interruptStreaming(sessionId);
    });

    const session = useBuildSessionStore.getState().sessions.get(sessionId);
    const toolStatuses = session?.streamItems
      .filter((item) => item.type === "tool_call")
      .map((item) => item.toolCall.status);

    expect(interruptMessageStream).toHaveBeenCalledWith(sessionId);
    expect(session?.isInterrupting).toBe(true);
    expect(session?.wasInterrupted).toBe(true);
    expect(toolStatuses).toEqual(["completed", "cancelled"]);
  });

  it("sets wasInterrupted on interrupt and clears it on the next turn", async () => {
    useBuildSessionStore.getState().updateSessionData(sessionId, {
      status: "running",
      activeTurnId: "turn-x",
      activeTurnLocalOwner: true,
    });
    const { result } = renderHook(() => useBuildStreaming());

    await act(async () => {
      await result.current.interruptStreaming(sessionId);
    });
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)?.wasInterrupted
    ).toBe(true);

    await act(async () => {
      await result.current.streamMessage(sessionId, "next");
    });
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)?.wasInterrupted
    ).toBe(false);
  });

  it("clears wasInterrupted when the interrupt request fails", async () => {
    const errorSpy = jest.spyOn(console, "error").mockImplementation(() => {});
    jest
      .mocked(interruptMessageStream)
      .mockRejectedValueOnce(new Error("network down"));
    useBuildSessionStore.getState().updateSessionData(sessionId, {
      status: "running",
      activeTurnId: "turn-x",
      activeTurnLocalOwner: true,
    });
    const { result } = renderHook(() => useBuildStreaming());

    await act(async () => {
      await result.current.interruptStreaming(sessionId);
    });

    const session = useBuildSessionStore.getState().sessions.get(sessionId);
    expect(session?.isInterrupting).toBe(false);
    expect(session?.wasInterrupted).toBe(false);
    errorSpy.mockRestore();
  });

  it("persists an interrupted in-flight tool call as cancelled on prompt_response", async () => {
    jest
      .mocked(processSSEStream)
      .mockImplementationOnce(async (_response, onPacket) => {
        onPacket({
          type: "tool_call_start",
          tool_call_id: "tool-active",
          kind: "execute",
          title: "Running command",
          content: null,
          locations: null,
          raw_input: null,
          raw_output: null,
          status: "pending",
          timestamp: "2026-01-01T00:00:00Z",
        } as never);
        useBuildSessionStore.getState().updateSessionData(sessionId, {
          isInterrupting: true,
        });
        onPacket({
          type: "tool_call_progress",
          tool_call_id: "tool-active",
          kind: "execute",
          raw_input: { command: "sleep 30" },
          raw_output: null,
          status: "in_progress",
          timestamp: "2026-01-01T00:00:00.500Z",
        } as never);
        onPacket({
          type: "prompt_response",
          timestamp: "2026-01-01T00:00:01Z",
        });
      });

    const { result } = renderHook(() => useBuildStreaming());

    await act(async () => {
      await result.current.streamMessage(sessionId, "build the app");
    });

    const session = useBuildSessionStore.getState().sessions.get(sessionId);
    const assistantMessage = session?.messages.find(
      (message) => message.type === "assistant"
    );
    const metadata = assistantMessage?.message_metadata as
      | { streamItems?: StreamItem[] }
      | undefined;

    expect(session?.streamItems).toEqual([]);
    // Settlement is deferred to reconcile, so isInterrupting stays set here.
    expect(session?.isInterrupting).toBe(true);
    expect(metadata?.streamItems).toEqual([
      expect.objectContaining({
        type: "tool_call",
        toolCall: expect.objectContaining({
          id: "tool-active",
          status: "cancelled",
        }),
      }),
    ]);
  });

  it("does not clear a newer turn when an older attach emits prompt_response late", async () => {
    jest
      .mocked(processSSEStream)
      .mockImplementationOnce(async (_response, onPacket) => {
        useBuildSessionStore.getState().updateSessionData(sessionId, {
          status: "running",
          activeTurnId: "turn-new",
          activeTurnLocalOwner: true,
        });
        onPacket({
          type: "prompt_response",
          timestamp: "2026-01-01T00:00:02Z",
        });
      });
    const { result } = renderHook(() => useBuildStreaming());

    await act(async () => {
      await result.current.streamTurnEvents(
        sessionId,
        "turn-old",
        new AbortController().signal
      );
    });

    const session = useBuildSessionStore.getState().sessions.get(sessionId);
    expect(session).toMatchObject({
      status: "running",
      activeTurnId: "turn-new",
      activeTurnLocalOwner: true,
    });
  });

  it("does not fail a newer turn when an older attach emits an error late", async () => {
    jest
      .mocked(processSSEStream)
      .mockImplementationOnce(async (_response, onPacket) => {
        useBuildSessionStore.getState().updateSessionData(sessionId, {
          status: "running",
          activeTurnId: "turn-new",
          activeTurnLocalOwner: true,
        });
        onPacket({
          type: "error",
          message: "old turn failed",
        } as never);
      });
    const { result } = renderHook(() => useBuildStreaming());

    await act(async () => {
      await result.current.streamTurnEvents(
        sessionId,
        "turn-old",
        new AbortController().signal
      );
    });

    const session = useBuildSessionStore.getState().sessions.get(sessionId);
    expect(session).toMatchObject({
      status: "running",
      activeTurnId: "turn-new",
      activeTurnLocalOwner: true,
      error: null,
    });
    expect(session?.streamItems).toEqual([]);
  });

  it("ends prior completion ownership when a new prompt is rejected", async () => {
    useBuildSessionStore.getState().updateSessionData(sessionId, {
      turnSettlement: {
        owner: { kind: "interactive", turnId: "completed-turn" },
        turnGeneration: 0,
        phase: "reconciling",
      },
      messages: [
        {
          id: "rejected-prompt",
          type: "user",
          content: "Keep this prompt",
          timestamp: new Date(),
        },
      ],
    });
    jest.mocked(createTurn).mockRejectedValueOnce(new Error("Send rejected"));
    const { result } = renderHook(() => useBuildStreaming());
    await act(async () => {
      await result.current.streamMessage(sessionId, "Keep this prompt");
    });
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)
    ).toMatchObject({
      turnSettlement: null,
      error: "Send rejected",
    });
    useBuildSessionStore.setState({ loadSession: originalLoadSession });
    useBuildSessionStore.getState().setCurrentSession("another-session");
    await act(async () =>
      useBuildSessionStore.getState().loadSession(sessionId)
    );
    expect(fetchMessages).not.toHaveBeenCalled();
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)?.messages
    ).toEqual([expect.objectContaining({ content: "Keep this prompt" })]);
  });

  it("clears local interrupt state when the backend active turn is gone", async () => {
    jest.mocked(interruptMessageStream).mockResolvedValueOnce(undefined);
    jest.mocked(fetchActiveTurn).mockResolvedValueOnce(null as never);
    useBuildSessionStore.getState().updateSessionData(sessionId, {
      status: "running",
      activeTurnId: "turn-interrupted",
      activeTurnIndex: 3,
      activeTurnLocalOwner: true,
      isInterrupting: false,
    });
    const { result } = renderHook(() => useBuildStreaming());

    await act(async () => {
      await result.current.interruptStreaming(sessionId);
    });

    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)
    ).toMatchObject({
      status: "running",
      activeTurnId: "turn-interrupted",
      isInterrupting: true,
    });

    await act(async () => {
      jest.advanceTimersByTime(1000);
      await Promise.resolve();
    });

    expect(fetchActiveTurn).toHaveBeenCalledWith(sessionId);
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)
    ).toMatchObject({
      status: "active",
      activeTurnId: null,
      activeTurnIndex: null,
      activeTurnLocalOwner: false,
      isInterrupting: false,
    });
    expect(fetchMessages).toHaveBeenCalledWith(sessionId);
  });

  it("reloads before flipping to active (avoids the auto-send TOCTOU)", async () => {
    jest.mocked(interruptMessageStream).mockResolvedValueOnce(undefined);
    jest.mocked(fetchActiveTurn).mockResolvedValueOnce(null as never);
    // Capture the session status at the moment loadSession runs. The flip to
    // "active" triggers the queued auto-send, so the reload must happen while
    // still "running" — before the flip — or it races the next turn.
    let statusAtLoad: string | undefined;
    jest.mocked(fetchMessages).mockImplementationOnce(async () => {
      statusAtLoad = useBuildSessionStore
        .getState()
        .sessions.get(sessionId)?.status;
      return [];
    });
    useBuildSessionStore.getState().updateSessionData(sessionId, {
      status: "running",
      activeTurnId: "turn-interrupted",
      activeTurnIndex: 3,
      activeTurnLocalOwner: true,
      isInterrupting: false,
    });
    const { result } = renderHook(() => useBuildStreaming());

    await act(async () => {
      await result.current.interruptStreaming(sessionId);
    });
    await act(async () => {
      jest.advanceTimersByTime(1000);
      await Promise.resolve();
    });

    expect(statusAtLoad).toBe("running");
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)?.status
    ).toBe("active");
  });

  it("bails a stale reconcile once a newer turn supersedes the interrupt", async () => {
    jest.mocked(interruptMessageStream).mockResolvedValueOnce(undefined);
    useBuildSessionStore.getState().updateSessionData(sessionId, {
      status: "running",
      activeTurnId: "turn-interrupted",
      activeTurnIndex: 3,
      activeTurnLocalOwner: true,
      isInterrupting: false,
      turnGeneration: 5,
    });
    const { result } = renderHook(() => useBuildStreaming());

    await act(async () => {
      await result.current.interruptStreaming(sessionId);
    });

    // A queued message auto-sends: a new turn starts and bumps turnGeneration.
    useBuildSessionStore.getState().updateSessionData(sessionId, {
      status: "running",
      activeTurnId: "turn-next",
      activeTurnLocalOwner: true,
      isInterrupting: false,
      turnGeneration: 6,
    });

    await act(async () => {
      jest.advanceTimersByTime(1000);
      await Promise.resolve();
    });

    // The stale reconcile must not poll or settle — the live turn is untouched.
    expect(fetchActiveTurn).not.toHaveBeenCalled();
    expect(useBuildSessionStore.getState().loadSession).not.toHaveBeenCalled();
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)
    ).toMatchObject({
      status: "running",
      activeTurnId: "turn-next",
    });
  });

  it("does not clear local interrupt state while the backend turn is still active", async () => {
    jest.mocked(interruptMessageStream).mockResolvedValueOnce(undefined);
    jest.mocked(fetchActiveTurn).mockResolvedValueOnce({
      session_id: sessionId,
      turn_id: "turn-interrupted",
      status: "RUNNING",
      turn_index: 3,
    } as never);
    useBuildSessionStore.getState().updateSessionData(sessionId, {
      status: "running",
      activeTurnId: "turn-interrupted",
      activeTurnIndex: 3,
      activeTurnLocalOwner: true,
      isInterrupting: false,
    });
    const { result } = renderHook(() => useBuildStreaming());

    await act(async () => {
      await result.current.interruptStreaming(sessionId);
    });
    await act(async () => {
      jest.advanceTimersByTime(1000);
      await Promise.resolve();
    });

    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)
    ).toMatchObject({
      status: "running",
      activeTurnId: "turn-interrupted",
      activeTurnLocalOwner: true,
      isInterrupting: true,
    });
    expect(useBuildSessionStore.getState().loadSession).not.toHaveBeenCalled();
    useBuildSessionStore.getState().updateSessionData(sessionId, {
      status: "active",
      isInterrupting: false,
    });
  });

  it("clears only interrupt state when a timed-out turn is still running", async () => {
    const warnSpy = jest.spyOn(console, "warn").mockImplementation(() => {});
    jest.mocked(interruptMessageStream).mockResolvedValueOnce(undefined);
    const activeTurn = {
      session_id: sessionId,
      turn_id: "turn-interrupted",
      status: "RUNNING",
      turn_index: 3,
    } as never;
    // 30 poll attempts + 1 final post-timeout check, all reporting the turn
    // still running.
    for (let attempt = 0; attempt < 31; attempt++) {
      jest.mocked(fetchActiveTurn).mockResolvedValueOnce(activeTurn);
    }
    useBuildSessionStore.getState().updateSessionData(sessionId, {
      status: "running",
      activeTurnId: "turn-interrupted",
      activeTurnIndex: 3,
      activeTurnLocalOwner: true,
      isInterrupting: false,
    });
    const { result } = renderHook(() => useBuildStreaming());

    await act(async () => {
      await result.current.interruptStreaming(sessionId);
    });
    for (let attempt = 0; attempt < 30; attempt++) {
      await act(async () => {
        jest.advanceTimersByTime(1000);
        await Promise.resolve();
      });
    }

    expect(fetchActiveTurn).toHaveBeenCalledTimes(31);
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)
    ).toMatchObject({
      status: "running",
      activeTurnId: "turn-interrupted",
      activeTurnLocalOwner: true,
      isInterrupting: false,
    });
    expect(useBuildSessionStore.getState().loadSession).not.toHaveBeenCalled();
    expect(warnSpy).toHaveBeenCalledWith(
      "[Streaming] Interrupted turn reconciliation timed out"
    );
    warnSpy.mockRestore();
  });

  it("settles a timed-out turn that the backend reports as gone", async () => {
    const warnSpy = jest.spyOn(console, "warn").mockImplementation(() => {});
    jest.mocked(interruptMessageStream).mockResolvedValueOnce(undefined);
    const activeTurn = {
      session_id: sessionId,
      turn_id: "turn-interrupted",
      status: "RUNNING",
      turn_index: 3,
    } as never;
    // 30 poll attempts report the turn still running, but the final
    // post-timeout check finds it gone → settle so the UI unblocks.
    for (let attempt = 0; attempt < 30; attempt++) {
      jest.mocked(fetchActiveTurn).mockResolvedValueOnce(activeTurn);
    }
    jest.mocked(fetchActiveTurn).mockResolvedValueOnce(null as never);
    useBuildSessionStore.getState().updateSessionData(sessionId, {
      status: "running",
      activeTurnId: "turn-interrupted",
      activeTurnIndex: 3,
      activeTurnLocalOwner: true,
      isInterrupting: false,
    });
    const { result } = renderHook(() => useBuildStreaming());

    await act(async () => {
      await result.current.interruptStreaming(sessionId);
    });
    for (let attempt = 0; attempt < 31; attempt++) {
      await act(async () => {
        jest.advanceTimersByTime(1000);
        await Promise.resolve();
      });
    }

    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)
    ).toMatchObject({
      status: "active",
      activeTurnId: null,
      activeTurnLocalOwner: false,
      isInterrupting: false,
    });
    expect(fetchMessages).toHaveBeenCalledWith(sessionId);
    warnSpy.mockRestore();
  });

  it("does not clear local state when backend reports a different active turn", async () => {
    jest.mocked(interruptMessageStream).mockResolvedValueOnce(undefined);
    jest.mocked(fetchActiveTurn).mockResolvedValueOnce({
      session_id: sessionId,
      turn_id: "turn-new",
      status: "RUNNING",
      turn_index: 4,
    } as never);
    useBuildSessionStore.getState().updateSessionData(sessionId, {
      status: "running",
      activeTurnId: "turn-interrupted",
      activeTurnIndex: 3,
      activeTurnLocalOwner: true,
      isInterrupting: false,
    });
    const { result } = renderHook(() => useBuildStreaming());

    await act(async () => {
      await result.current.interruptStreaming(sessionId);
    });
    await act(async () => {
      jest.advanceTimersByTime(1000);
      await Promise.resolve();
    });

    expect(fetchActiveTurn).toHaveBeenCalledTimes(1);
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)
    ).toMatchObject({
      status: "running",
      activeTurnId: "turn-interrupted",
      activeTurnIndex: 3,
      activeTurnLocalOwner: true,
      isInterrupting: true,
    });
    expect(useBuildSessionStore.getState().loadSession).not.toHaveBeenCalled();
    useBuildSessionStore.getState().updateSessionData(sessionId, {
      status: "active",
      isInterrupting: false,
    });
  });

  it("keeps polling until the interrupted backend turn is gone", async () => {
    jest.mocked(interruptMessageStream).mockResolvedValueOnce(undefined);
    jest.mocked(fetchOutputInventory).mockResolvedValue({
      complete: true,
      files: [{ path: "outputs/stopped.pdf", revision: "1", size: 100 }],
    });
    jest
      .mocked(fetchActiveTurn)
      .mockResolvedValueOnce({
        session_id: sessionId,
        turn_id: "turn-interrupted",
        status: "RUNNING",
        turn_index: 3,
      } as never)
      .mockResolvedValueOnce(null as never);
    useBuildSessionStore.getState().updateSessionData(sessionId, {
      status: "running",
      activeTurnId: "turn-interrupted",
      activeTurnIndex: 3,
      activeTurnLocalOwner: true,
      isInterrupting: false,
    });
    const { result } = renderHook(() => useBuildStreaming());

    await act(async () => {
      await result.current.interruptStreaming(sessionId);
    });
    await act(async () => {
      jest.advanceTimersByTime(1000);
      await Promise.resolve();
    });

    expect(useBuildSessionStore.getState().loadSession).not.toHaveBeenCalled();

    await act(async () => {
      jest.advanceTimersByTime(1000);
      await Promise.resolve();
    });

    expect(fetchActiveTurn).toHaveBeenCalledTimes(3);
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)
    ).toMatchObject({
      status: "active",
      activeTurnId: null,
      activeTurnLocalOwner: false,
      isInterrupting: false,
    });
    expect(fetchMessages).toHaveBeenCalledWith(sessionId);
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)
        ?.outputInventory?.["outputs/stopped.pdf"]
    ).toBeDefined();
  });

  it("reconciles an accepted backend turn after Stop", async () => {
    jest.mocked(interruptMessageStream).mockResolvedValueOnce(undefined);
    jest.mocked(fetchOutputInventory).mockResolvedValue({
      files: [{ path: "outputs/stopped.pdf", revision: "1", size: 100 }],
      complete: true,
    });
    jest
      .mocked(fetchActiveTurn)
      .mockResolvedValueOnce({
        session_id: sessionId,
        turn_id: "turn-created-after-interrupt",
        status: "RUNNING",
        turn_index: 3,
      } as never)
      .mockResolvedValueOnce(null as never);
    useBuildSessionStore.getState().updateSessionData(sessionId, {
      status: "running",
      activeTurnId: "turn-created-after-interrupt",
      activeTurnIndex: null,
      activeTurnLocalOwner: false,
      isInterrupting: false,
    });
    const { result } = renderHook(() => useBuildStreaming());

    await act(async () => {
      await result.current.interruptStreaming(sessionId);
    });
    await act(async () => {
      jest.advanceTimersByTime(1000);
      await Promise.resolve();
    });
    await act(async () => {
      jest.advanceTimersByTime(1000);
      await Promise.resolve();
    });

    expect(fetchActiveTurn).toHaveBeenCalledTimes(3);
    expect(fetchOutputInventory).toHaveBeenCalledWith(
      sessionId,
      expect.any(AbortSignal)
    );
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)
        ?.outputInventory?.["outputs/stopped.pdf"]
    ).toBeDefined();
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)
    ).toMatchObject({
      status: "active",
      activeTurnId: null,
      activeTurnLocalOwner: false,
      isInterrupting: false,
    });
  });
  it("holds the queue after failed settlement and dispatches once after retry", async () => {
    const store = useBuildSessionStore.getState();
    store.enqueueMessage(sessionId, "queued prompt", []);
    store.updateSessionData(sessionId, {
      status: "running",
      activeTurnId: "completed-turn",
      turnGeneration: 1,
    });
    jest
      .mocked(fetchMessages)
      .mockRejectedValueOnce(new Error("history unavailable"));
    jest.mocked(processSSEStream).mockImplementation(async () => {});
    const { result } = renderHook(() => useBuildStreaming());
    await act(async () => {
      await result.current.interruptStreaming(sessionId);
      await jest.advanceTimersByTimeAsync(1000);
    });
    expect(createTurn).not.toHaveBeenCalled();
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)?.turnSettlement
    ).toMatchObject({ phase: "failed" });
    await act(async () => {
      await store.retryTurnSettlement(sessionId);
    });
    expect(createTurn).toHaveBeenCalledTimes(1);
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)?.queuedMessages
    ).toEqual([]);
    expect(
      useBuildSessionStore
        .getState()
        .sessions.get(sessionId)
        ?.messages.filter((message) => message.content === "queued prompt")
    ).toHaveLength(1);
    expect(result.current.retryQueuedMessage).toBeDefined();
  });

  it("keeps rejected queued work and retries its stable request without duplicating messages", async () => {
    const store = useBuildSessionStore.getState();
    const model = {
      providerId: 7,
      providerName: "Selected",
      provider: "anthropic",
      modelName: "selected-model",
    };
    store.enqueueMessage(sessionId, "retained prompt", [], model);
    store.updateSessionData(sessionId, {
      turnSettlement: {
        owner: { kind: "interactive", turnId: "old-turn" },
        turnGeneration: 0,
        phase: "ready",
      },
    });
    jest.mocked(createTurn).mockRejectedValueOnce(new Error("POST rejected"));
    jest.mocked(processSSEStream).mockImplementation(async () => {});
    const { result, rerender } = renderHook(() => useBuildStreaming());
    await act(async () => {});
    const pending = useBuildSessionStore.getState().sessions.get(sessionId)
      ?.queuedMessages[0];
    expect(pending).toMatchObject({
      text: "retained prompt",
      phase: "failed",
    });
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)?.messages
    ).toEqual([]);
    rerender();
    expect(createTurn).toHaveBeenCalledTimes(1);
    const requestId = jest.mocked(createTurn).mock.calls[0]?.[2];
    await act(async () => {
      await result.current.retryQueuedMessage(sessionId);
    });
    expect(createTurn).toHaveBeenCalledTimes(2);
    expect(jest.mocked(createTurn).mock.calls[1]?.[2]).toBe(requestId);
    expect(jest.mocked(createTurn).mock.calls[0]?.[4]).toEqual(model);
    expect(jest.mocked(createTurn).mock.calls[1]?.[4]).toEqual(model);
    expect(
      useBuildSessionStore
        .getState()
        .sessions.get(sessionId)
        ?.messages.filter((message) => message.content === "retained prompt")
    ).toHaveLength(1);
  });

  it("retains ready permission across unmount and dispatches without changing navigation", async () => {
    const store = useBuildSessionStore.getState();
    const first = renderHook(() => useBuildStreaming());
    first.unmount();
    store.enqueueMessage(sessionId, "background prompt", []);
    store.updateSessionData(sessionId, {
      turnSettlement: {
        owner: { kind: "interactive", turnId: "old-turn" },
        turnGeneration: 0,
        phase: "ready",
      },
    });
    store.createSession("visible-session");
    store.setCurrentSession("visible-session");
    jest.mocked(processSSEStream).mockImplementation(async () => {});
    renderHook(() => useBuildStreaming());
    renderHook(() => useBuildStreaming());
    await act(async () => {});
    expect(createTurn).toHaveBeenCalledTimes(1);
    expect(useBuildSessionStore.getState().currentSessionId).toBe(
      "visible-session"
    );
  });

  it("dispatches FIFO only after each backend turn has committed", async () => {
    const store = useBuildSessionStore.getState();
    store.enqueueMessage(sessionId, "first queued", []);
    store.enqueueMessage(sessionId, "second queued", []);
    store.updateSessionData(sessionId, {
      turnSettlement: {
        owner: { kind: "interactive", turnId: "old-turn" },
        turnGeneration: 0,
        phase: "ready",
      },
      loadError: "Metadata unavailable",
    });
    jest
      .mocked(fetchActiveTurn)
      .mockResolvedValue({ turn_id: "turn-thinking", turn_index: 0 } as never);
    jest.mocked(processSSEStream).mockImplementation(async () => {});
    renderHook(() => useBuildStreaming());
    await act(async () => {});
    expect(createTurn).toHaveBeenCalledTimes(1);
    expect(jest.mocked(createTurn).mock.calls[0]?.[1]).toBe("first queued");
    expect(
      useBuildSessionStore
        .getState()
        .sessions.get(sessionId)
        ?.queuedMessages.map((message) => message.text)
    ).toEqual(["second queued"]);
    jest.mocked(fetchActiveTurn).mockResolvedValue(null);
    await act(async () => {
      await jest.advanceTimersByTimeAsync(1000);
    });
    expect(createTurn).toHaveBeenCalledTimes(2);
    expect(jest.mocked(createTurn).mock.calls[1]?.[1]).toBe("second queued");
  });

  it("does not remove a queue head whose POST has started", async () => {
    const store = useBuildSessionStore.getState();
    store.enqueueMessage(sessionId, "starting prompt", []);
    store.updateSessionData(sessionId, {
      turnSettlement: {
        owner: { kind: "interactive", turnId: "old-turn" },
        turnGeneration: 0,
        phase: "ready",
      },
    });
    jest.mocked(createTurn).mockImplementation(() => new Promise(() => {}));
    renderHook(() => useBuildStreaming());
    const head = useBuildSessionStore.getState().sessions.get(sessionId)
      ?.queuedMessages[0];
    expect(head?.phase).toBe("starting");
    act(() => {
      if (head) store.removeQueuedMessage(sessionId, head.id);
    });
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)?.queuedMessages[0]
        ?.id
    ).toBe(head?.id);
  });

  it("keeps Stop intent until a pending POST accepts, then stops that accepted turn", async () => {
    let accept:
      | ((turn: Awaited<ReturnType<typeof createTurn>>) => void)
      | undefined;
    jest.mocked(createTurn).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          accept = resolve;
        })
    );
    jest.mocked(processSSEStream).mockImplementation(async () => {});
    const { result } = renderHook(() => useBuildStreaming());
    let sending: Promise<void> | undefined;
    act(() => {
      sending = result.current.streamMessage(sessionId, "starting request");
    });
    await act(async () => {
      await result.current.interruptStreaming(sessionId);
      await jest.advanceTimersByTimeAsync(1000);
    });
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)
    ).toMatchObject({ isInterrupting: true, turnSettlement: null });
    await act(async () => {
      accept?.({
        session_id: sessionId,
        turn_id: "accepted-after-stop",
        status: "QUEUED",
        turn_index: 0,
      });
      await sending;
      await jest.advanceTimersByTimeAsync(1000);
    });
    expect(interruptMessageStream).toHaveBeenCalledTimes(2);
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)
    ).toMatchObject({
      status: "active",
      isInterrupting: false,
      turnSettlement: { phase: "ready" },
    });
  });

  it("does not retry untouched queued work after a normal prompt POST fails", async () => {
    let reject: ((error: Error) => void) | undefined;
    jest.mocked(createTurn).mockImplementationOnce(
      () =>
        new Promise((_resolve, rejectPromise) => {
          reject = rejectPromise;
        })
    );
    const { result } = renderHook(() => useBuildStreaming());
    let sending: Promise<void> | undefined;
    act(() => {
      sending = result.current.streamMessage(sessionId, "original prompt");
    });
    act(() => {
      useBuildSessionStore
        .getState()
        .enqueueMessage(sessionId, "untouched queue", []);
    });
    await act(async () => {
      reject?.(new Error("Original rejected"));
      await sending;
    });
    await act(async () => {
      await result.current.retryQueuedMessage(sessionId);
    });
    expect(createTurn).toHaveBeenCalledTimes(1);
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)?.queuedMessages[0]
    ).toMatchObject({ text: "untouched queue", phase: "waiting" });
  });

  it("reconnects a clean live EOF without resetting streamed text", async () => {
    jest.mocked(fetchActiveTurn).mockResolvedValue({
      session_id: sessionId,
      turn_id: "turn-thinking",
      status: "RUNNING",
      turn_index: 0,
    });
    jest
      .mocked(processSSEStream)
      .mockImplementationOnce(async (_response, onPacket) => {
        onPacket({
          sessionUpdate: "agent_message_chunk",
          content: { type: "text", text: "Before reconnect. " },
        } as never);
      })
      .mockImplementationOnce(async (_response, onPacket) => {
        onPacket({
          sessionUpdate: "agent_message_chunk",
          content: { type: "text", text: "After reconnect." },
        } as never);
        onPacket({ type: "prompt_response" } as never);
      });
    const { result } = renderHook(() => useBuildStreaming());
    let streaming: Promise<void> | undefined;
    act(() => {
      streaming = result.current.streamMessage(sessionId, "reconnect");
    });
    await act(async () => {});
    expect(fetchTurnEventStream).toHaveBeenCalledTimes(1);
    jest.mocked(fetchActiveTurn).mockResolvedValue(null);
    await act(async () => {
      await jest.advanceTimersByTimeAsync(1000);
      await streaming;
    });
    expect(fetchTurnEventStream).toHaveBeenCalledTimes(2);
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)?.messages
    ).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          content: "Before reconnect. After reconnect.",
        }),
      ])
    );
  });

  it("adopts a successor server turn without releasing queued prompts", async () => {
    const store = useBuildSessionStore.getState();
    store.enqueueMessage(sessionId, "held queue", []);
    store.updateSessionData(sessionId, {
      status: "running",
      turnGeneration: 1,
      outputSelectionLocked: true,
      wasInterrupted: true,
    });
    jest.mocked(fetchActiveTurn).mockResolvedValue({
      session_id: sessionId,
      turn_id: "other-tab-turn",
      status: "RUNNING",
      turn_index: 1,
    });
    renderHook(() => useBuildStreaming());
    await act(async () => {
      await store.beginTurnSettlement(
        sessionId,
        { kind: "interactive", turnId: "completed-turn" },
        1
      );
    });
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)
    ).toMatchObject({
      status: "running",
      activeTurnId: "other-tab-turn",
      turnGeneration: 2,
      outputSelectionLocked: false,
      wasInterrupted: false,
      turnSettlement: null,
    });
    expect(createTurn).not.toHaveBeenCalled();
  });

  it("keeps an accepted turn active when the repeated Stop request fails", async () => {
    let accept:
      | ((turn: Awaited<ReturnType<typeof createTurn>>) => void)
      | undefined;
    jest.mocked(createTurn).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          accept = resolve;
        })
    );
    jest
      .mocked(interruptMessageStream)
      .mockResolvedValueOnce(undefined)
      .mockRejectedValueOnce(new Error("Stop unavailable"));
    jest
      .mocked(processSSEStream)
      .mockRejectedValueOnce(new DOMException("Viewer closed", "AbortError"));
    const { result } = renderHook(() => useBuildStreaming());
    let sending: Promise<void> | undefined;
    act(() => {
      sending = result.current.streamMessage(sessionId, "accepted request");
    });
    await act(async () => {
      await result.current.interruptStreaming(sessionId);
    });
    await act(async () => {
      accept?.({
        session_id: sessionId,
        turn_id: "accepted-turn",
        status: "QUEUED",
        turn_index: 0,
      });
      await sending;
    });
    expect(interruptMessageStream).toHaveBeenCalledTimes(2);
    expect(fetchTurnEventStream).toHaveBeenCalledTimes(1);
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)
    ).toMatchObject({
      status: "running",
      activeTurnId: "accepted-turn",
      isInterrupting: false,
      error: null,
    });
  });

  it("ignores a delayed inactive response from an old attachment", async () => {
    let close: ((response: Response | null) => void) | undefined;
    jest.mocked(fetchTurnEventStream).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          close = resolve;
        })
    );
    const { result } = renderHook(() => useBuildStreaming());
    let attached: Promise<void> | undefined;
    act(() => {
      attached = result.current.streamTurnEvents(
        sessionId,
        "old-turn",
        new AbortController().signal
      );
    });
    act(() => {
      useBuildSessionStore.getState().updateSessionData(sessionId, {
        status: "running",
        turnGeneration: 1,
        activeTurnId: "new-turn",
        activeTurnLocalOwner: true,
      });
    });
    await act(async () => {
      close?.(null);
      await attached;
    });
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)
    ).toMatchObject({
      status: "running",
      turnGeneration: 1,
      activeTurnId: "new-turn",
      activeTurnLocalOwner: true,
      turnSettlement: null,
    });
    expect(fetchActiveTurn).not.toHaveBeenCalled();
    expect(fetchMessages).not.toHaveBeenCalled();
  });

  it.each(["aborted", "successor"] as const)(
    "ignores a late scheduled transport error after %s ownership",
    async (change) => {
      let reject: ((error: Error) => void) | undefined;
      jest.mocked(fetchScheduledRunEventStream).mockImplementationOnce(
        () =>
          new Promise((_resolve, rejectPromise) => {
            reject = rejectPromise;
          })
      );
      const controller = new AbortController();
      const settled = jest.fn();
      const { result } = renderHook(() => useBuildStreaming());
      let streaming: Promise<void> | undefined;
      act(() => {
        streaming = result.current.streamScheduledRunEvents(
          sessionId,
          "scheduled-run",
          controller.signal,
          settled
        );
      });
      act(() => {
        if (change === "aborted") {
          controller.abort();
          useBuildSessionStore
            .getState()
            .updateSessionData(sessionId, { status: "active" });
        } else {
          useBuildSessionStore.getState().updateSessionData(sessionId, {
            status: "running",
            turnGeneration: 1,
            activeTurnId: "interactive-successor",
            activeTurnLocalOwner: true,
          });
        }
      });
      await act(async () => {
        reject?.(new Error("Late proxy rejection"));
        await streaming;
      });
      expect(
        useBuildSessionStore.getState().sessions.get(sessionId)
      ).toMatchObject({
        status: change === "aborted" ? "active" : "running",
        error: null,
        turnGeneration: change === "aborted" ? 0 : 1,
        activeTurnId: change === "aborted" ? null : "interactive-successor",
        turnSettlement: null,
      });
      expect(settled).not.toHaveBeenCalled();
      expect(fetchScheduledRunContext).not.toHaveBeenCalled();
    }
  );

  it.each(["resolve", "reject"] as const)(
    "ignores an old repeated Stop that later %ss after queued ownership advances",
    async (outcome) => {
      let accept:
        | ((turn: Awaited<ReturnType<typeof createTurn>>) => void)
        | undefined;
      let completeStop: (() => void) | undefined;
      let failStop: ((error: Error) => void) | undefined;
      jest.mocked(createTurn).mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            accept = resolve;
          })
      );
      jest
        .mocked(interruptMessageStream)
        .mockResolvedValueOnce(undefined)
        .mockImplementationOnce(
          () =>
            new Promise((resolve, reject) => {
              completeStop = resolve;
              failStop = reject;
            })
        );
      jest
        .mocked(processSSEStream)
        .mockImplementation(() => new Promise(() => {}));
      const { result } = renderHook(() => useBuildStreaming());
      let oldStart: Promise<void> | undefined;
      act(() => {
        oldStart = result.current.streamMessage(sessionId, "old request");
      });
      act(() => {
        useBuildSessionStore
          .getState()
          .enqueueMessage(sessionId, "queued successor", []);
      });
      await act(async () => {
        await result.current.interruptStreaming(sessionId);
      });
      await act(async () => {
        accept?.({
          session_id: sessionId,
          turn_id: "old-turn",
          status: "QUEUED",
          turn_index: 0,
        });
      });
      expect(interruptMessageStream).toHaveBeenCalledTimes(2);
      await act(async () => {
        await jest.advanceTimersByTimeAsync(1000);
      });
      expect(createTurn).toHaveBeenCalledTimes(2);
      act(() => {
        useBuildSessionStore.getState().updateSessionData(sessionId, {
          isInterrupting: true,
          wasInterrupted: true,
        });
        useBuildSessionStore.getState().appendStreamItem(sessionId, {
          type: "text",
          id: "successor-text",
          content: "New output",
          isStreaming: true,
        });
      });
      const successor = useBuildSessionStore.getState().sessions.get(sessionId);
      await act(async () => {
        if (outcome === "resolve") completeStop?.();
        else failStop?.(new Error("Late Stop failure"));
        await oldStart;
      });
      expect(useBuildSessionStore.getState().sessions.get(sessionId)).toBe(
        successor
      );
      expect(fetchTurnEventStream).toHaveBeenCalledTimes(1);
    }
  );

  it("keeps output discovery alive across a nonterminal EOF", async () => {
    jest.mocked(fetchActiveTurn).mockResolvedValue({
      session_id: sessionId,
      turn_id: "turn-thinking",
      status: "RUNNING",
      turn_index: 0,
    });
    jest
      .mocked(processSSEStream)
      .mockImplementationOnce(async () => {})
      .mockImplementationOnce(async (_response, onPacket) => {
        jest.mocked(fetchOutputInventory).mockResolvedValue({
          complete: true,
          files: [{ path: "outputs/late.pdf", revision: "1", size: 100 }],
        });
        onPacket({
          type: "tool_call_progress",
          tool_call_id: "late-write",
          kind: "edit",
          status: "completed",
          raw_input: { filePath: "outputs/late.pdf" },
          raw_output: null,
          _meta: { toolName: "write" },
        } as never);
        onPacket({ type: "prompt_response" } as never);
      });
    const { result } = renderHook(() => useBuildStreaming());
    let streaming: Promise<void> | undefined;
    act(() => {
      streaming = result.current.streamMessage(sessionId, "late deliverable");
    });
    await act(async () => {});
    expect(fetchOutputInventory).not.toHaveBeenCalled();
    jest.mocked(fetchActiveTurn).mockResolvedValue(null);
    await act(async () => {
      await jest.advanceTimersByTimeAsync(1000);
      await streaming;
    });
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)
        ?.outputInventory?.["outputs/late.pdf"]
    ).toBeDefined();
  });
  it("reconciles authoritative text parts across reconnects without losing order", async () => {
    jest.mocked(fetchActiveTurn).mockResolvedValue({
      session_id: sessionId,
      turn_id: "turn-thinking",
      status: "RUNNING",
      turn_index: 0,
    });
    jest
      .mocked(processSSEStream)
      .mockImplementationOnce(async (_response, onPacket) => {
        const emit = <P extends { type: string }>(packet: P) =>
          onPacket(packet);
        emit({
          type: "agent_message_chunk",
          content: { type: "text", text: "Hello" },
          _meta: { partId: "first" },
        });
        emit({
          type: "tool_call_start",
          toolCallId: "between-parts",
          title: "Read file",
          kind: "read",
        });
      })
      .mockImplementationOnce(async (_response, onPacket) => {
        const emit = <P extends { type: string }>(packet: P) =>
          onPacket(packet);
        const text = (partId: string, value: string, snapshotText?: string) =>
          emit({
            type: "agent_message_chunk",
            content: { type: "text", text: value },
            _meta: {
              partId,
              ...(snapshotText === undefined ? {} : { snapshotText }),
            },
          });
        text("first", " world");
        text("first", "Hello world", "Hello world");
        text("first", "", "Hello world");
        emit({
          type: "agent_thought_chunk",
          content: { type: "text", text: "Reason" },
          _meta: { partId: "thought" },
        });
        emit({
          type: "agent_thought_chunk",
          content: { type: "text", text: "Reasoning" },
          _meta: { partId: "thought", snapshotText: "Reasoning" },
        });
        text("second", "New answer");
        text("first", "!", "Hello world!");
        throw Object.assign(new Error("fixture disconnect"), {
          name: "AbortError",
        });
      });
    const { result } = renderHook(() => useBuildStreaming());
    let streaming: Promise<void> | undefined;
    act(() => {
      streaming = result.current.streamMessage(sessionId, "build");
    });
    await act(async () => {});
    await act(async () => {
      await jest.advanceTimersByTimeAsync(1000);
      await streaming;
    });
    expect(fetchTurnEventStream).toHaveBeenCalledTimes(2);
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)?.streamItems
    ).toEqual([
      expect.objectContaining({
        type: "text",
        partId: "first",
        content: "Hello world!",
      }),
      expect.objectContaining({
        type: "tool_call",
        toolCall: expect.objectContaining({ id: "between-parts" }),
      }),
      expect.objectContaining({
        type: "thinking",
        partId: "thought",
        content: "Reasoning",
      }),
      expect.objectContaining({
        type: "text",
        partId: "second",
        content: "New answer",
      }),
    ]);
  });

  it("hands a failed EOF status check to completion polling before releasing queued work", async () => {
    const active: NonNullable<Awaited<ReturnType<typeof fetchActiveTurn>>> = {
      session_id: sessionId,
      turn_id: "turn-thinking",
      status: "RUNNING",
      turn_index: 0,
    };
    jest
      .mocked(fetchActiveTurn)
      .mockRejectedValueOnce(new Error("temporary status failure"))
      .mockResolvedValueOnce(active)
      .mockResolvedValue(null);
    jest.mocked(processSSEStream).mockResolvedValue(undefined);
    jest.mocked(fetchOutputInventory).mockResolvedValue({
      complete: true,
      files: [{ path: "outputs/recovered.pdf", revision: "1", size: 10 }],
    });
    const { result } = renderHook(() => useBuildStreaming());
    let sending: Promise<void> | undefined;
    act(() => {
      sending = result.current.streamMessage(sessionId, "original");
    });
    act(() => {
      useBuildSessionStore.getState().enqueueMessage(sessionId, "next", []);
    });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(createTurn).toHaveBeenCalledTimes(1);
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)?.queuedMessages
    ).toHaveLength(1);
    await act(async () => {
      await jest.advanceTimersByTimeAsync(1000);
      await sending;
    });
    expect(createTurn).toHaveBeenCalledTimes(2);
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)?.queuedMessages
    ).toEqual([]);
    expect(useBuildSessionStore.getState().loadSession).not.toHaveBeenCalled();
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)
        ?.outputInventory?.["outputs/recovered.pdf"]
    ).toBeDefined();
  });
  it("retains queued work until an explicit retry recovers failed completion polling", async () => {
    jest
      .mocked(fetchActiveTurn)
      .mockRejectedValueOnce(new Error("status offline"))
      .mockRejectedValueOnce(new Error("completion offline"));
    jest.mocked(processSSEStream).mockResolvedValue(undefined);
    const { result } = renderHook(() => useBuildStreaming());
    let sending: Promise<void> | undefined;
    act(() => {
      sending = result.current.streamMessage(sessionId, "original");
    });
    act(() => {
      useBuildSessionStore.getState().enqueueMessage(sessionId, "queued", []);
    });
    await act(async () => {
      await sending;
    });
    expect(createTurn).toHaveBeenCalledTimes(1);
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)
    ).toMatchObject({
      turnSettlement: expect.objectContaining({ phase: "failed" }),
      queuedMessages: [
        expect.objectContaining({ text: "queued", phase: "waiting" }),
      ],
    });
    jest.mocked(fetchActiveTurn).mockResolvedValue(null);
    await act(async () => {
      await useBuildSessionStore.getState().retryTurnSettlement(sessionId);
    });
    expect(createTurn).toHaveBeenCalledTimes(2);
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)?.queuedMessages
    ).toEqual([]);
  });
  it("keeps Stop ownership when an outstanding stream read fails", async () => {
    let failRead: ((error: Error) => void) | undefined;
    jest.mocked(processSSEStream).mockImplementationOnce(
      () =>
        new Promise((_resolve, reject) => {
          failRead = reject;
        })
    );
    const { result } = renderHook(() => useBuildStreaming());
    let sending: Promise<void> | undefined;
    act(() => {
      sending = result.current.streamMessage(sessionId, "original");
    });
    await act(async () => {});
    await act(async () => {
      await result.current.interruptStreaming(sessionId);
    });
    await act(async () => {
      failRead?.(new Error("disconnected during Stop"));
      await sending;
    });
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)
    ).toMatchObject({
      isInterrupting: true,
      wasInterrupted: true,
      turnSettlement: null,
    });
    await act(async () => {
      await jest.advanceTimersByTimeAsync(1000);
    });
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)
    ).toMatchObject({
      isInterrupting: false,
      turnSettlement: expect.objectContaining({ phase: "ready" }),
    });
  });
  it("ignores a delayed Stop rejection after a successor owns the session", async () => {
    let rejectStop: ((error: Error) => void) | undefined;
    jest.mocked(interruptMessageStream).mockImplementationOnce(
      () =>
        new Promise((_resolve, reject) => {
          rejectStop = reject;
        })
    );
    useBuildSessionStore.getState().updateSessionData(sessionId, {
      status: "running",
      activeTurnId: "old",
      activeTurnLocalOwner: true,
    });
    const { result } = renderHook(() => useBuildStreaming());
    let stopping: Promise<void> | undefined;
    act(() => {
      stopping = result.current.interruptStreaming(sessionId);
    });
    const generation = useBuildSessionStore
      .getState()
      .sessions.get(sessionId)!.turnGeneration;
    act(() => {
      useBuildSessionStore.getState().updateSessionData(sessionId, {
        activeTurnId: "successor",
        turnGeneration: generation + 1,
        isInterrupting: true,
        wasInterrupted: true,
      });
    });
    const successor = useBuildSessionStore.getState().sessions.get(sessionId);
    await act(async () => {
      rejectStop?.(new Error("old Stop rejected"));
      await stopping;
    });
    expect(useBuildSessionStore.getState().sessions.get(sessionId)).toBe(
      successor
    );
  });
  it.each(["SUCCEEDED", "FAILED"] as const)(
    "reconciles worker %s after a scheduled transport failure",
    async (workerStatus) => {
      jest
        .mocked(fetchScheduledRunEventStream)
        .mockRejectedValueOnce(new Error("Transient proxy failure"));
      const run = {
        run_id: "scheduled-run",
        task_id: "task",
        task_name: "Task",
        started_at: "2026-10-10T00:00:00Z",
        finished_at: null,
      };
      jest
        .mocked(fetchScheduledRunContext)
        .mockResolvedValueOnce({ ...run, status: "RUNNING" })
        .mockResolvedValue({ ...run, status: workerStatus });
      const saved = [
        {
          id: "saved-result",
          type: "assistant" as const,
          content: "Saved worker result",
          timestamp: new Date(),
          message_metadata: {
            type: "agent_message",
            content: {
              type: "text",
              text: "Saved worker result",
            },
          },
        },
      ];
      jest.mocked(fetchMessages).mockResolvedValue(saved);
      const { result } = renderHook(() => useBuildStreaming());
      let streaming: Promise<void> | undefined;
      act(() => {
        streaming = result.current.streamScheduledRunEvents(
          sessionId,
          "scheduled-run",
          new AbortController().signal
        );
      });
      await act(async () => {});
      expect(
        useBuildSessionStore.getState().sessions.get(sessionId)
      ).toMatchObject({
        status: "running",
        error: null,
        turnSettlement: { phase: "reconciling" },
      });
      await act(async () => {
        await jest.advanceTimersByTimeAsync(1000);
        await streaming;
      });
      const session = useBuildSessionStore.getState().sessions.get(sessionId);
      expect(session?.error).toBeNull();
      if (workerStatus === "SUCCEEDED") {
        expect(session?.turnSettlement?.phase).toBe("ready");
        expect(session?.messages).toEqual([
          expect.objectContaining({ content: "Saved worker result" }),
        ]);
      } else {
        expect(session?.status).toBe("failed");
        expect(session?.turnSettlement).toBeNull();
        expect(fetchMessages).toHaveBeenCalledTimes(1);
        expect(session?.messages).toEqual([
          expect.objectContaining({ content: "Saved worker result" }),
        ]);
      }
    }
  );
  it.each(["text", "thinking"] as const)(
    "restores an identified child %s prefix before applying its live snapshot",
    async (type) => {
      useBuildSessionStore.setState({ loadSession: originalLoadSession });
      jest.mocked(fetchSession).mockResolvedValue({
        id: sessionId,
        user_id: null,
        name: null,
        status: "active",
        created_at: "2026-10-12T00:00:00Z",
        last_activity_at: "2026-10-12T00:00:00Z",
        nextjs_port: null,
        sandbox: null,
        artifacts: [],
        sharing_scope: "private",
        origin: "INTERACTIVE",
        agent_provider: null,
        agent_model: null,
        skills_stale: false,
        session_loaded_in_sandbox: true,
      });
      jest.mocked(fetchArtifacts).mockResolvedValue([]);
      jest.mocked(fetchActiveTurn).mockResolvedValue({
        session_id: sessionId,
        turn_id: "restored",
        turn_index: 0,
        status: "RUNNING",
      });
      const packets: Awaited<ReturnType<typeof fetchMessages>> = [
        {
          id: "user",
          type: "user",
          content: "Run parallel agents",
          timestamp: new Date(),
          turn_index: 0,
        },
        ...["Hello", " world"].map((text, index) => ({
          id: `child-prefix-${index}`,
          type: "assistant" as const,
          content: "",
          timestamp: new Date(),
          turn_index: 0,
          message_metadata: {
            type: type === "text" ? "agent_message" : "agent_thought",
            content: { type: "text", text },
            _meta: {
              partId: "part-a",
              sessionId: "child-a",
              parentSessionId: "parent",
            },
          },
        })),
      ];
      jest.mocked(fetchMessages).mockResolvedValue(packets);
      await act(async () => {
        await useBuildSessionStore
          .getState()
          .loadSession(sessionId, { force: true });
      });
      const child = () =>
        useBuildSessionStore
          .getState()
          .sessions.get(sessionId)
          ?.subagents.get("child-a")?.turns[0];
      expect(child()?.streamItems).toEqual([
        expect.objectContaining({
          type,
          partId: "part-a",
          content: "Hello world",
        }),
      ]);
      jest
        .mocked(processSSEStream)
        .mockImplementationOnce(async (_response, onPacket) => {
          const snapshot = {
            type:
              type === "text" ? "agent_message_chunk" : "agent_thought_chunk",
            content: { type: "text", text: "Hello world!" },
            _meta: {
              partId: "part-a",
              snapshotText: "Hello world!",
              sessionId: "child-a",
              parentSessionId: "parent",
            },
          };
          onPacket(snapshot);
          throw Object.assign(new Error("fixture disconnect"), {
            name: "AbortError",
          });
        });
      const { result } = renderHook(() => useBuildStreaming());
      await act(async () => {
        await result.current.streamTurnEvents(
          sessionId,
          "restored",
          new AbortController().signal
        );
      });
      expect(child()?.streamItems).toEqual([
        expect.objectContaining({
          type,
          partId: "part-a",
          content: "Hello world!",
        }),
      ]);
      expect(type === "text" ? child()?.response : child()?.thinking).toBe(
        "Hello world!"
      );
    }
  );
  it.each(["text", "thinking"] as const)(
    "restores an identified parent %s prefix before applying its live snapshot",
    async (type) => {
      useBuildSessionStore.setState({ loadSession: originalLoadSession });
      jest.mocked(fetchSession).mockResolvedValue({
        id: sessionId,
        user_id: null,
        name: null,
        status: "active",
        created_at: "2026-10-12T00:00:00Z",
        last_activity_at: "2026-10-12T00:00:00Z",
        nextjs_port: null,
        sandbox: null,
        artifacts: [],
        sharing_scope: "private",
        origin: "INTERACTIVE",
        agent_provider: null,
        agent_model: null,
        skills_stale: false,
        session_loaded_in_sandbox: true,
      });
      jest.mocked(fetchArtifacts).mockResolvedValue([]);
      jest.mocked(fetchActiveTurn).mockResolvedValue({
        session_id: sessionId,
        turn_id: "restored",
        turn_index: 0,
        status: "RUNNING",
      });
      const packets: Awaited<ReturnType<typeof fetchMessages>> = [
        {
          id: "user",
          type: "user",
          content: "Run parallel agents",
          timestamp: new Date(),
          turn_index: 0,
        },
        ...["Hello", " world"].map((text, index) => ({
          id: `child-prefix-${index}`,
          type: "assistant" as const,
          content: "",
          timestamp: new Date(),
          turn_index: 0,
          message_metadata: {
            type: type === "text" ? "agent_message" : "agent_thought",
            content: { type: "text", text },
            _meta: { partId: "part-a" },
          },
        })),
      ];
      jest.mocked(fetchMessages).mockResolvedValue(packets);
      await act(async () => {
        await useBuildSessionStore
          .getState()
          .loadSession(sessionId, { force: true });
      });
      const items = () =>
        useBuildSessionStore.getState().sessions.get(sessionId)?.streamItems;
      expect(items()).toEqual([
        expect.objectContaining({
          type,
          partId: "part-a",
          content: "Hello world",
        }),
      ]);
      jest
        .mocked(processSSEStream)
        .mockImplementationOnce(async (_response, onPacket) => {
          const snapshot = {
            type:
              type === "text" ? "agent_message_chunk" : "agent_thought_chunk",
            content: { type: "text", text: "Hello world!" },
            _meta: {
              partId: "part-a",
              snapshotText: "Hello world!",
            },
          };
          onPacket(snapshot);
          throw Object.assign(new Error("fixture disconnect"), {
            name: "AbortError",
          });
        });
      const { result } = renderHook(() => useBuildStreaming());
      await act(async () => {
        await result.current.streamTurnEvents(
          sessionId,
          "restored",
          new AbortController().signal
        );
      });
      expect(items()).toEqual([
        expect.objectContaining({
          type,
          partId: "part-a",
          content: "Hello world!",
        }),
      ]);
    }
  );
  it("starts queued work while completion inventory is pending without losing files or stealing focus", async () => {
    let completeFirst: (() => void) | undefined;
    let finishFirst: (() => void) | undefined;
    let finishNext: (() => void) | undefined;
    let finishInventory:
      | ((value: Awaited<ReturnType<typeof fetchOutputInventory>>) => void)
      | undefined;
    const firstStream = new Promise<void>((resolve) => {
      finishFirst = resolve;
    });
    const nextStream = new Promise<void>((resolve) => {
      finishNext = resolve;
    });
    const finalInventory = new Promise<
      Awaited<ReturnType<typeof fetchOutputInventory>>
    >((resolve) => {
      finishInventory = resolve;
    });
    const selected = {
      kind: "file" as const,
      path: "outputs/chosen.pdf",
      fileName: "chosen.pdf",
    };
    useBuildSessionStore.getState().updateSessionData(sessionId, {
      outputInventory: {},
      outputBaselinePending: false,
      panelTabs: [selected],
      activePanelTabId: "file:outputs/chosen.pdf",
    });
    jest.mocked(fetchOutputInventory).mockReturnValueOnce(finalInventory);
    jest
      .mocked(processSSEStream)
      .mockImplementationOnce(async () => {
        completeFirst = () => finishFirst?.();
        await firstStream;
        throw new Error("Transport disconnected before terminal packet");
      })
      .mockImplementationOnce(async () => {
        await nextStream;
        throw new DOMException("Closed", "AbortError");
      });
    const { result } = renderHook(() => useBuildStreaming());
    let sending: Promise<void> | undefined;
    act(() => {
      sending = result.current.streamMessage(sessionId, "first");
    });
    await act(async () => {});
    act(() => {
      useBuildSessionStore.getState().enqueueMessage(sessionId, "next", []);
    });
    await act(async () => {
      completeFirst?.();
      await sending;
    });
    expect(fetchOutputInventory).toHaveBeenCalledTimes(1);
    expect(createTurn).toHaveBeenCalledTimes(2);
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)?.turnGeneration
    ).toBe(2);
    await act(async () => {
      finishInventory?.({
        files: [{ path: "outputs/completed.pdf", revision: "1", size: 10 }],
        complete: true,
      });
    });
    const session = useBuildSessionStore.getState().sessions.get(sessionId);
    expect(session?.outputInventory?.["outputs/completed.pdf"]).toBeDefined();
    expect(session?.panelTabs).toEqual([selected]);
    expect(session?.activePanelTabId).toBe("file:outputs/chosen.pdf");
    await act(async () => {
      useBuildSessionStore.getState().abortSession(sessionId);
      finishNext?.();
    });
  });
  it("reconciles a terminal packet after pending Stop fails before releasing queued work", async () => {
    let terminal: (() => void) | undefined;
    let finishStream: (() => void) | undefined;
    let failStop: ((error: Error) => void) | undefined;
    let finishNext: (() => void) | undefined;
    const first = new Promise<void>((resolve) => {
      finishStream = resolve;
    });
    const next = new Promise<void>((resolve) => {
      finishNext = resolve;
    });
    jest.mocked(interruptMessageStream).mockReturnValueOnce(
      new Promise((_resolve, reject) => {
        failStop = reject;
      })
    );
    jest
      .mocked(processSSEStream)
      .mockImplementationOnce(async (_response, onPacket) => {
        terminal = () => {
          onPacket({ type: "prompt_response" });
          finishStream?.();
        };
        await first;
      })
      .mockImplementationOnce(async () => {
        await next;
        throw new DOMException("Closed", "AbortError");
      });
    const { result } = renderHook(() => useBuildStreaming());
    let sending: Promise<void> | undefined;
    let stopping: Promise<void> | undefined;
    act(() => {
      sending = result.current.streamMessage(sessionId, "first");
    });
    await act(async () => {});
    act(() => {
      useBuildSessionStore.getState().enqueueMessage(sessionId, "next", []);
      stopping = result.current.interruptStreaming(sessionId);
    });
    await act(async () => {
      terminal?.();
      await sending;
    });
    expect(createTurn).toHaveBeenCalledTimes(1);
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)?.turnSettlement
    ).toBeNull();
    await act(async () => {
      failStop?.(new Error("Stop request failed"));
      await stopping;
    });
    expect(createTurn).toHaveBeenCalledTimes(1);
    await act(async () => {
      await jest.advanceTimersByTimeAsync(1000);
    });
    expect(createTurn).toHaveBeenCalledTimes(2);
    expect(fetchMessages).toHaveBeenCalledTimes(1);
    await act(async () => {
      useBuildSessionStore.getState().abortSession(sessionId);
      finishNext?.();
    });
  });

  it("yields failed Stop completion polling to a new Stop on the same running turn", async () => {
    let acceptNext: (() => void) | undefined;
    jest
      .mocked(interruptMessageStream)
      .mockRejectedValueOnce(new Error("First Stop rejected"))
      .mockReturnValueOnce(
        new Promise((resolve) => {
          acceptNext = resolve;
        })
      );
    jest.mocked(fetchActiveTurn).mockResolvedValue({
      session_id: sessionId,
      turn_id: "running",
      status: "RUNNING",
      turn_index: 0,
    });
    useBuildSessionStore.getState().updateSessionData(sessionId, {
      status: "running",
      activeTurnId: "running",
      activeTurnLocalOwner: true,
    });
    const { result } = renderHook(() => useBuildStreaming());
    await act(async () => {
      await result.current.interruptStreaming(sessionId);
    });
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)?.isInterrupting
    ).toBe(false);
    let stopping: Promise<void> | undefined;
    act(() => {
      stopping = result.current.interruptStreaming(sessionId);
    });
    await act(async () => {
      await jest.advanceTimersByTimeAsync(31000);
    });
    expect(fetchActiveTurn).not.toHaveBeenCalled();
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)?.isInterrupting
    ).toBe(true);
    jest.mocked(fetchActiveTurn).mockResolvedValue(null);
    await act(async () => {
      acceptNext?.();
      await stopping;
      await jest.advanceTimersByTimeAsync(1000);
    });
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)
    ).toMatchObject({
      status: "active",
      isInterrupting: false,
      turnSettlement: { phase: "ready" },
    });
  });

  it("does not post Stop while completion settlement owns a session without an active turn", async () => {
    useBuildSessionStore.getState().updateSessionData(sessionId, {
      status: "running",
      activeTurnId: null,
      activeTurnLocalOwner: false,
      turnSettlement: {
        owner: { kind: "interactive", turnId: "completed" },
        turnGeneration: 0,
        phase: "reconciling",
      },
    });
    const { result } = renderHook(() => useBuildStreaming());
    await act(async () => {
      await result.current.interruptStreaming(sessionId);
    });
    expect(interruptMessageStream).not.toHaveBeenCalled();
  });
  it("reconciles a scheduled in-band error through its worker before reading partial history", async () => {
    jest.useFakeTimers();
    try {
      const run = {
        run_id: "scheduled-run",
        task_id: "task",
        task_name: "Task",
        started_at: "2026-10-12T00:00:00Z",
        finished_at: null,
      };
      jest
        .mocked(fetchScheduledRunContext)
        .mockResolvedValueOnce({ ...run, status: "RUNNING" })
        .mockResolvedValue({ ...run, status: "FAILED" });
      const saved = [
        {
          id: "partial-result",
          type: "assistant" as const,
          content: "Persisted partial result",
          timestamp: new Date(),
          message_metadata: {
            type: "agent_message",
            content: { type: "text", text: "Persisted partial result" },
          },
        },
      ];
      jest.mocked(fetchMessages).mockResolvedValue(saved);
      jest
        .mocked(processSSEStream)
        .mockImplementationOnce(async (_response, onPacket) => {
          const packet = { type: "error", message: "Worker failed" };
          onPacket(packet);
        });
      useBuildSessionStore
        .getState()
        .enqueueMessage(sessionId, "waiting prompt", []);
      const { result } = renderHook(() => useBuildStreaming());
      await act(async () => {
        await result.current.streamScheduledRunEvents(
          sessionId,
          "scheduled-run",
          new AbortController().signal
        );
      });
      expect(fetchMessages).not.toHaveBeenCalled();
      expect(
        useBuildSessionStore.getState().sessions.get(sessionId)
      ).toMatchObject({
        status: "running",
        error: null,
        turnSettlement: { phase: "reconciling" },
      });
      await act(async () => {
        await jest.advanceTimersByTimeAsync(1000);
      });
      expect(fetchActiveTurn).not.toHaveBeenCalled();
      expect(
        useBuildSessionStore.getState().sessions.get(sessionId)
      ).toMatchObject({
        status: "failed",
        error: null,
        turnSettlement: null,
        messages: [
          expect.objectContaining({ content: "Persisted partial result" }),
        ],
      });
      expect(createTurn).not.toHaveBeenCalled();
      expect(
        useBuildSessionStore.getState().sessions.get(sessionId)?.queuedMessages
      ).toHaveLength(1);
    } finally {
      jest.useRealTimers();
    }
  });
});
