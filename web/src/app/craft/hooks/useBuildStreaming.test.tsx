import { act, renderHook } from "@testing-library/react";

import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import { useBuildStreaming } from "@/app/craft/hooks/useBuildStreaming";
import type { StreamItem } from "@/app/craft/types/displayTypes";
import {
  createTurn,
  fetchActiveTurn,
  fetchArtifacts,
  fetchMessages,
  fetchSession,
  fetchTurnEventStream,
  interruptMessageStream,
  processSSEStream,
} from "@/app/craft/services/apiServices";

jest.mock("swr", () => ({
  useSWRConfig: () => ({ mutate: jest.fn() }),
}));

jest.mock("@/app/craft/services/apiServices", () => ({
  RateLimitError: class RateLimitError extends Error {},
  createTurn: jest.fn(),
  fetchActiveTurn: jest.fn(),
  fetchArtifacts: jest.fn(),
  fetchMessages: jest.fn(),
  fetchScheduledRunEventStream: jest.fn(),
  fetchSession: jest.fn(),
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
    });

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

  it("seeds clickable subagent metadata from a task start packet", async () => {
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

  it("replaces placeholder subagent metadata when task progress names the child", async () => {
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

  it("keeps active turn metadata when attach transport fails", async () => {
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
      status: "running",
      activeTurnId: "turn-failed",
      activeTurnLocalOwner: false,
    });
    expect(useBuildSessionStore.getState().loadSession).toHaveBeenCalledWith(
      sessionId,
      { force: true }
    );
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
    expect(useBuildSessionStore.getState().loadSession).toHaveBeenCalledWith(
      sessionId,
      { force: true }
    );
  });

  it("clears interrupt state when an attached stream settles", async () => {
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

    const session = useBuildSessionStore.getState().sessions.get(sessionId);
    expect(session).toMatchObject({
      status: "active",
      activeTurnId: null,
      activeTurnLocalOwner: false,
      isInterrupting: false,
    });
    expect(useBuildSessionStore.getState().loadSession).toHaveBeenCalledWith(
      sessionId,
      { force: true }
    );
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
      session_loaded_in_sandbox: true,
      sandbox: { id: "sandbox-1", status: "running", nextjs_port: null },
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
    expect(toolStatuses).toEqual(["completed", "cancelled"]);
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
    expect(session?.isInterrupting).toBe(false);
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
    expect(useBuildSessionStore.getState().loadSession).toHaveBeenCalledWith(
      sessionId,
      { force: true }
    );
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

  it("clears only interrupt state when interrupted turn reconciliation times out", async () => {
    const warnSpy = jest.spyOn(console, "warn").mockImplementation(() => {});
    jest.mocked(interruptMessageStream).mockResolvedValueOnce(undefined);
    const activeTurn = {
      session_id: sessionId,
      turn_id: "turn-interrupted",
      status: "RUNNING",
      turn_index: 3,
    } as never;
    for (let attempt = 0; attempt < 30; attempt++) {
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

    expect(fetchActiveTurn).toHaveBeenCalledTimes(30);
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

    expect(fetchActiveTurn).toHaveBeenCalledTimes(2);
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)
    ).toMatchObject({
      status: "active",
      activeTurnId: null,
      activeTurnLocalOwner: false,
      isInterrupting: false,
    });
    expect(useBuildSessionStore.getState().loadSession).toHaveBeenCalledWith(
      sessionId,
      { force: true }
    );
  });

  it("reconciles interrupts before the local active turn id is known", async () => {
    jest.mocked(interruptMessageStream).mockResolvedValueOnce(undefined);
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
      activeTurnId: null,
      activeTurnIndex: null,
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
    await act(async () => {
      jest.advanceTimersByTime(1000);
      await Promise.resolve();
    });

    expect(fetchActiveTurn).toHaveBeenCalledTimes(2);
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)
    ).toMatchObject({
      status: "active",
      activeTurnId: null,
      activeTurnLocalOwner: false,
      isInterrupting: false,
    });
  });
});
