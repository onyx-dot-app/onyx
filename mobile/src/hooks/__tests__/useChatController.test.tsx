import { beforeEach, describe, expect, it, jest } from "@jest/globals";
import type { Mock } from "jest-mock";
import * as React from "react";
import { act, renderHook, waitFor } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { router } from "expo-router";

import { postQuestionAnswers } from "@/api/chat/questions";
import { ApiError } from "@/api/errors";
import {
  createChatSession,
  getChatSession,
  getChatSessionStatus,
  renameChatSession,
  stopChatSession,
} from "@/api/chat/sessions";
import {
  resumeChatMessage,
  streamChatMessage,
  StreamHttpError,
  type StreamEvent,
} from "@/api/chat/stream";
import { ChatFileType, type FileDescriptor } from "@/chat/interfaces";
import { PacketType, StopReason } from "@/chat/streamingModels";
import { getLatestMessageChain } from "@/chat/messageTree";
import {
  readToolApprovals,
  toolApprovalStatus,
  useToolApprovalUi,
} from "@/chat/toolApprovals";
import { readToolQuestions, useToolQuestionUi } from "@/chat/toolQuestions";
import { followUserAnswer } from "@/hooks/followUserAnswer";
import { useChatController } from "@/hooks/useChatController";
import { toast } from "@/hooks/useToast";
import { useChatSessionStore } from "@/state/chatSessionStore";

// `jest.mock` is hoisted above the imports by babel-jest, so the imports above receive the mocks.
jest.mock("expo-router", () => ({
  router: { replace: jest.fn(), navigate: jest.fn() },
}));
jest.mock("@/state/session", () => ({
  useSession: (selector: (s: { serverUrl: string | null }) => unknown) =>
    selector({ serverUrl: "https://example.test" }),
}));
// Re-implement the trivial discriminators inline so we don't pull in expo/fetch.
jest.mock("@/api/chat/stream", () => ({
  streamChatMessage: jest.fn(),
  resumeChatMessage: jest.fn(),
  isHeartbeat: (event: { obj?: { type?: string } }) =>
    event.obj?.type === "chat_heartbeat",
  isPacket: (event: { obj?: unknown; placement?: unknown }) =>
    "obj" in event && "placement" in event,
  isMessageIdInfo: (event: { user_message_id?: unknown }) =>
    "user_message_id" in event,
  isStreamCursor: (event: { next_cursor?: unknown }) => "next_cursor" in event,
  isStreamError: (event: { error?: unknown }) =>
    "error" in event && typeof event.error === "string",
  StreamHttpError: class StreamHttpError extends Error {
    status: number;
    code: string | null;
    constructor(message: string, status: number, code: string | null = null) {
      super(message);
      this.status = status;
      this.code = code;
    }
  },
}));
jest.mock("@/api/chat/sessions", () => ({
  createChatSession: jest.fn(),
  getChatSession: jest.fn(),
  getChatSessionStatus: jest.fn(async () => ({ is_processing: false })),
  renameChatSession: jest.fn(),
  stopChatSession: jest.fn(),
}));
// Status polls wait this long instead of the real interval, so tests do not sleep.
jest.mock("@/chat/constants", () => ({
  ...jest.requireActual<typeof import("@/chat/constants")>("@/chat/constants"),
  SESSION_POLL_INTERVAL_MS: 10,
}));
jest.mock("@/api/chat/questions", () => ({ postQuestionAnswers: jest.fn() }));
jest.mock("@/hooks/followUserAnswer", () => ({ followUserAnswer: jest.fn() }));
jest.mock("@/hooks/useToast", () => ({
  toast: { info: jest.fn(), error: jest.fn(), warning: jest.fn() },
}));

const streamMock = streamChatMessage as unknown as Mock<
  (body: { origin: string }, signal: AbortSignal) => AsyncGenerator<StreamEvent>
>;
const resumeMock = resumeChatMessage as unknown as Mock<
  (
    id: string,
    streamId: number,
    cursor: number,
    signal: AbortSignal,
  ) => AsyncGenerator<StreamEvent>
>;
const createSessionMock = createChatSession as unknown as Mock<
  (personaId?: number, projectId?: number | null) => Promise<string>
>;
const getSessionMock = getChatSession as unknown as Mock<
  (id: string) => Promise<unknown>
>;
const stopSessionMock = stopChatSession as unknown as Mock<
  (id: string, streamId?: number) => Promise<void>
>;
const renameSessionMock = renameChatSession as unknown as Mock<
  (id: string) => Promise<void>
>;

function startPacket(content: string): StreamEvent {
  return {
    placement: { turn_index: 0 },
    obj: { type: PacketType.MESSAGE_START, id: "m", content },
  } as StreamEvent;
}
const pausedStop = {
  placement: { turn_index: 0 },
  obj: { type: PacketType.STOP, stop_reason: StopReason.AWAITING_USER },
} as StreamEvent;
const approvalRequest = {
  placement: { turn_index: 0 },
  obj: {
    type: PacketType.TOOL_APPROVAL_REQUEST,
    approval_id: "a1",
    tool_call_id: "c1",
    tool_name: "lookup",
    display_name: "Lookup",
    arguments: {},
  },
} as StreamEvent;
function deltaPacket(content: string): StreamEvent {
  return {
    placement: { turn_index: 0 },
    obj: { type: PacketType.MESSAGE_DELTA, content },
  } as StreamEvent;
}
function stopPacket(): StreamEvent {
  return {
    placement: { turn_index: 0 },
    obj: { type: PacketType.STOP },
  } as StreamEvent;
}
function endPacket(): StreamEvent {
  return {
    placement: { turn_index: 0 },
    obj: { type: PacketType.MESSAGE_END },
  } as StreamEvent;
}
const idInfo = {
  user_message_id: 10,
  reserved_assistant_message_id: 11,
} as StreamEvent;
function cursor(streamId: number, nextCursor: number): StreamEvent {
  return {
    stream_id: streamId,
    next_cursor: nextCursor,
    replay_complete: true,
  };
}
function streamError(error: string, errorCode?: string): StreamEvent {
  return { error, error_code: errorCode ?? null } as unknown as StreamEvent;
}

// The saved session of one question (10) and its answer (11).
function savedTurn(packets: unknown[], answer = "") {
  return {
    chat_session_id: "s1",
    description: "",
    persona_id: 0,
    messages: [
      {
        message_id: 10,
        message_type: "user",
        parent_message: null,
        latest_child_message: 11,
        message: "Question",
        files: [],
        time_sent: "",
        error: null,
      },
      {
        message_id: 11,
        message_type: "assistant",
        parent_message: 10,
        latest_child_message: null,
        message: answer,
        files: [],
        time_sent: "",
        error: null,
      },
    ],
    packets: [packets],
    time_created: "",
    current_stream: null,
  };
}

// The requests that the latest response of session s1 shows as waiting.
function waitingIds(): string[] {
  const tree = useChatSessionStore.getState().sessions.get("s1")?.messageTree;
  const response = tree ? getLatestMessageChain(tree).at(-1) : undefined;
  const { localStatuses } = useToolApprovalUi.getState();
  return readToolApprovals(response?.packets ?? [])
    .filter(
      (entry) =>
        toolApprovalStatus(
          entry,
          localStatuses.get(entry.request.approval_id),
        ) === "pending",
    )
    .map((entry) => entry.request.approval_id);
}

async function* scripted(events: StreamEvent[]): AsyncGenerator<StreamEvent> {
  for (const event of events) yield event;
}

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function accumulated(packets: { obj: { type: string; content?: string } }[]) {
  return packets
    .filter(
      (p) =>
        p.obj.type === PacketType.MESSAGE_START ||
        p.obj.type === PacketType.MESSAGE_DELTA,
    )
    .map((p) => p.obj.content ?? "")
    .join("");
}

describe("useChatController", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    jest
      .mocked(getChatSessionStatus)
      .mockReset()
      .mockResolvedValue({ is_processing: false });
    renameSessionMock.mockResolvedValue();
    useChatSessionStore.setState({
      currentSessionId: null,
      sessions: new Map(),
    });
    useToolApprovalUi.setState({ localStatuses: new Map(), nudgeSeq: 0 });
  });

  it("sends while a tool approval waits, then keeps the draft when the server refuses", async () => {
    useChatSessionStore.getState().ensureSession("s1");
    getSessionMock.mockResolvedValue(savedTurn([approvalRequest, pausedStop]));
    streamMock
      .mockReturnValueOnce(scripted([idInfo, approvalRequest, pausedStop]))
      .mockReturnValueOnce(
        (async function* (): AsyncGenerator<StreamEvent> {
          throw new StreamHttpError("Waiting.", 409, "APPROVAL_PENDING");
        })(),
      );
    const onAccepted = jest.fn();
    const { result } = renderHook(() => useChatController("s1"), { wrapper });
    await act(async () => {
      await result.current.submit("Question");
    });
    await waitFor(() => expect(result.current.chatState).toBe("input"));

    await act(async () => {
      await result.current.submit("Follow-up", [], onAccepted);
    });
    await waitFor(() => expect(result.current.chatState).toBe("input"));

    expect(streamMock).toHaveBeenCalledTimes(2);
    expect(onAccepted).not.toHaveBeenCalled();
    expect(toast.warning).toHaveBeenCalledWith(
      "Answer the questions or decide the tool calls that wait first.",
    );
    expect(useToolApprovalUi.getState().nudgeSeq).toBe(1);
    expect(result.current.messages.map((m) => m.message)).toEqual([
      "Question",
      "",
    ]);
    expect(waitingIds()).toEqual(["a1"]);
  });

  it("releases input when a response pauses for approval, keeping its card open", async () => {
    useChatSessionStore.getState().ensureSession("s1");
    streamMock.mockReturnValueOnce(
      scripted([
        idInfo,
        approvalRequest,
        {
          placement: { turn_index: 0 },
          obj: {
            type: PacketType.STOP,
            stop_reason: StopReason.AWAITING_USER,
          },
        } as StreamEvent,
      ]),
    );
    const { result } = renderHook(() => useChatController("s1"), { wrapper });
    await act(async () => {
      await result.current.submit("Question");
    });

    await waitFor(() => expect(result.current.chatState).toBe("input"));
    expect(waitingIds()).toEqual(["a1"]);
    expect(result.current.messages[1]?.streamingStartedAt).toBeUndefined();
    expect(getSessionMock).not.toHaveBeenCalled();
  });

  it("reattaches to the run when the connection drops while an approval waits", async () => {
    useChatSessionStore.getState().ensureSession("s1");
    useChatSessionStore.setState({ currentSessionId: "s1" });
    jest
      .mocked(getChatSessionStatus)
      .mockResolvedValueOnce({ is_processing: false })
      .mockResolvedValue({
        is_processing: true,
        current_stream: { stream_id: 11, response_ids: [11] },
      });
    streamMock.mockReturnValueOnce(
      (async function* (): AsyncGenerator<StreamEvent> {
        yield idInfo;
        yield approvalRequest;
        throw new TypeError("Network request failed");
      })(),
    );
    let endReplay: () => void = () => {};
    resumeMock.mockReturnValueOnce(
      (async function* (): AsyncGenerator<StreamEvent> {
        yield approvalRequest;
        yield cursor(11, 1);
        await new Promise<void>((resolve) => {
          endReplay = resolve;
        });
      })(),
    );
    const { result } = renderHook(() => useChatController("s1"), { wrapper });
    await act(async () => {
      await result.current.submit("Question");
    });

    await waitFor(() =>
      expect(resumeMock).toHaveBeenCalledWith("s1", 11, 0, expect.anything()),
    );
    // The card stays reachable: the response is still a live answer, not an error.
    await waitFor(() => expect(waitingIds()).toEqual(["a1"]));
    expect(result.current.messages.map((m) => m.type)).toEqual([
      "user",
      "assistant",
    ]);
    expect(result.current.chatState).toBe("streaming");
    useChatSessionStore.setState({ currentSessionId: null });
    await act(async () => endReplay());
  });

  it("reloads the saved answer when a lost send finds the server already idle", async () => {
    useChatSessionStore.getState().ensureSession("s1");
    streamMock.mockReturnValueOnce(
      (async function* (): AsyncGenerator<StreamEvent> {
        yield idInfo;
        yield startPacket("Part");
        yield approvalRequest;
        throw new TypeError("Network request failed");
      })(),
    );
    getSessionMock.mockResolvedValue(
      savedTurn(
        [
          startPacket("Part of the answer"),
          approvalRequest,
          {
            placement: { turn_index: 0 },
            obj: {
              type: PacketType.TOOL_APPROVAL_RESOLVED,
              approval_id: "a1",
              outcome: "rejected",
            },
          },
          stopPacket(),
        ],
        "Part of the answer",
      ),
    );
    const { result } = renderHook(() => useChatController("s1"), { wrapper });
    await act(async () => {
      await result.current.submit("Question");
    });

    await waitFor(() => expect(result.current.chatState).toBe("input"));
    expect(getSessionMock).toHaveBeenCalledWith("s1");
    expect(resumeMock).not.toHaveBeenCalled();
    expect(accumulated(result.current.messages[1]!.packets)).toBe(
      "Part of the answer",
    );
    expect(waitingIds()).toEqual([]);
  });

  it("does not let a failed response's request block the next send", async () => {
    let now = Date.now();
    const clock = jest.spyOn(Date, "now").mockImplementation(() => (now += 10));
    useChatSessionStore.getState().ensureSession("s1");
    streamMock
      .mockReturnValueOnce(
        scripted([idInfo, approvalRequest, streamError("Boom.")]),
      )
      .mockReturnValueOnce(
        scripted([
          { user_message_id: 12, reserved_assistant_message_id: 13 },
          endPacket(),
          stopPacket(),
        ] as StreamEvent[]),
      );
    const { result } = renderHook(() => useChatController("s1"), { wrapper });
    await act(async () => {
      await result.current.submit("Question");
    });
    await waitFor(() => expect(result.current.chatState).toBe("input"));

    await act(async () => {
      await result.current.submit("try again");
    });

    expect(streamMock).toHaveBeenCalledTimes(2);
    expect(toast.warning).not.toHaveBeenCalled();
    clock.mockRestore();
  });

  it("loads the waiting card when the server refuses a send", async () => {
    useChatSessionStore.getState().ensureSession("s1");
    getSessionMock.mockResolvedValue(savedTurn([approvalRequest, pausedStop]));
    streamMock.mockReturnValueOnce(
      (async function* (): AsyncGenerator<StreamEvent> {
        throw new StreamHttpError("Waiting.", 409, "APPROVAL_PENDING");
      })(),
    );
    const onAccepted = jest.fn();
    const { result } = renderHook(() => useChatController("s1"), { wrapper });

    await act(async () => {
      await result.current.submit("Question", [], onAccepted);
    });
    await waitFor(() => expect(waitingIds()).toEqual(["a1"]));
    await waitFor(() => expect(result.current.chatState).toBe("input"));

    expect(getSessionMock).toHaveBeenCalledWith("s1");
    expect(result.current.messages.map((m) => m.message)).toEqual([
      "Question",
      "",
    ]);
    expect(onAccepted).not.toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();
    expect(toast.warning).toHaveBeenCalledWith(
      "Answer the questions or decide the tool calls that wait first.",
    );
  });

  it("loads and follows the waiting response when the server refuses a send", async () => {
    useChatSessionStore.getState().ensureSession("s1");
    jest
      .mocked(getChatSessionStatus)
      .mockResolvedValueOnce({ is_processing: false })
      .mockResolvedValue({
        is_processing: true,
        current_stream: { stream_id: 21, response_ids: [21] },
      });
    streamMock.mockReturnValueOnce(
      (async function* (): AsyncGenerator<StreamEvent> {
        throw new StreamHttpError("Waiting.", 409, "APPROVAL_PENDING");
      })(),
    );
    getSessionMock.mockResolvedValueOnce({
      chat_session_id: "s1",
      description: "",
      persona_id: 0,
      messages: [
        {
          message_id: 20,
          message_type: "user",
          parent_message: null,
          latest_child_message: 21,
          message: "Asked elsewhere",
          files: [],
          time_sent: "",
          error: null,
        },
        {
          message_id: 21,
          message_type: "assistant",
          parent_message: 20,
          latest_child_message: null,
          message: "",
          files: [],
          time_sent: "",
          error: null,
        },
      ],
      packets: [[]],
      time_created: "",
      current_stream: { stream_id: 21, response_ids: [21] },
    });
    let endReplay: () => void = () => {};
    resumeMock.mockReturnValueOnce(
      (async function* (): AsyncGenerator<StreamEvent> {
        yield approvalRequest;
        yield cursor(21, 1);
        await new Promise<void>((resolve) => {
          endReplay = resolve;
        });
      })(),
    );
    const onAccepted = jest.fn();
    const { result } = renderHook(() => useChatController("s1"), { wrapper });

    await act(async () => {
      await result.current.submit("Question", [], onAccepted);
    });

    await waitFor(() => expect(waitingIds()).toEqual(["a1"]));
    expect(resumeMock).toHaveBeenCalledWith("s1", 21, 0, expect.anything());
    expect(result.current.messages.map((m) => m.message)).toEqual([
      "Asked elsewhere",
      "",
    ]);
    expect(onAccepted).not.toHaveBeenCalled();
    expect(toast.warning).toHaveBeenCalledWith(
      "Answer the questions or decide the tool calls that wait first.",
    );
    useChatSessionStore.setState({ currentSessionId: null });
    await act(async () => endReplay());
  });

  it("stops the stream it follows after switching to one it cannot load", async () => {
    useChatSessionStore.getState().ensureSession("s1");
    useChatSessionStore.setState({ currentSessionId: "s1" });
    jest
      .mocked(getChatSessionStatus)
      .mockResolvedValueOnce({ is_processing: false })
      .mockResolvedValueOnce({
        is_processing: true,
        current_stream: { stream_id: 11, response_ids: [11] },
      })
      .mockResolvedValue({
        is_processing: true,
        current_stream: { stream_id: 21, response_ids: [21] },
      });
    streamMock.mockReturnValueOnce(
      (async function* (): AsyncGenerator<StreamEvent> {
        yield idInfo;
        throw new TypeError("Network request failed");
      })(),
    );
    resumeMock.mockReturnValueOnce(
      (async function* (): AsyncGenerator<StreamEvent> {
        throw new StreamHttpError("no resumable run", 404);
      })(),
    );
    getSessionMock.mockRejectedValue(new Error("offline"));
    stopSessionMock.mockResolvedValue();
    const warn = jest.spyOn(console, "warn").mockImplementation(() => {});
    const { result } = renderHook(() => useChatController("s1"), { wrapper });

    await act(async () => {
      await result.current.submit("Question");
    });
    await waitFor(() => expect(getSessionMock).toHaveBeenCalled());
    act(() => result.current.stop());

    await waitFor(() => expect(stopSessionMock).toHaveBeenCalled());
    expect(stopSessionMock).toHaveBeenCalledWith("s1", 21);
    useChatSessionStore.setState({ currentSessionId: null });
    warn.mockRestore();
  });

  it("does not follow a lost run again after the server confirms Stop", async () => {
    useChatSessionStore.getState().ensureSession("s1");
    const status = Promise.withResolvers<{
      is_processing: boolean;
      current_stream: { stream_id: number; response_ids: number[] };
    }>();
    jest
      .mocked(getChatSessionStatus)
      .mockResolvedValueOnce({ is_processing: false })
      .mockReturnValueOnce(status.promise)
      .mockResolvedValue({ is_processing: false });
    streamMock.mockReturnValueOnce(
      (async function* (): AsyncGenerator<StreamEvent> {
        yield idInfo;
        yield approvalRequest;
        throw new TypeError("Network request failed");
      })(),
    );
    stopSessionMock.mockResolvedValue();
    getSessionMock.mockResolvedValue(savedTurn([]));
    const { result } = renderHook(() => useChatController("s1"), { wrapper });
    await act(async () => {
      await result.current.submit("Question");
    });
    await waitFor(() => expect(result.current.chatState).toBe("settling"));

    act(() => result.current.stop());
    await waitFor(() => expect(stopSessionMock).toHaveBeenCalledWith("s1", 11));
    await act(async () => {
      status.resolve({
        is_processing: true,
        current_stream: { stream_id: 11, response_ids: [11] },
      });
    });

    await waitFor(() => expect(result.current.chatState).toBe("input"), {
      timeout: 3000,
    });
    expect(resumeMock).not.toHaveBeenCalled();
  });

  it("streams tokens into the assistant node and assigns message ids", async () => {
    useChatSessionStore.getState().ensureSession("s1");
    streamMock.mockReturnValue(
      scripted([
        startPacket("Hello"),
        deltaPacket(" world"),
        idInfo,
        endPacket(),
        stopPacket(),
      ]),
    );

    const { result } = renderHook(() => useChatController("s1"), { wrapper });

    await act(async () => {
      await result.current.submit("hi");
    });

    await waitFor(() => expect(result.current.chatState).toBe("input"));

    const messages = result.current.messages;
    expect(messages.map((m) => m.type)).toEqual(["user", "assistant"]);
    expect(messages[0]!.message).toBe("hi");
    expect(messages[0]!.messageId).toBe(10);
    expect(messages[1]!.messageId).toBe(11);
    expect(accumulated(messages[1]!.packets)).toBe("Hello world");

    const body = streamMock.mock.calls[0]![0];
    expect(body.origin).toBe("mobile");
    expect(
      (body as unknown as { parent_message_id: number | null })
        .parent_message_id,
    ).toBeNull();
  });

  it("stamps streamingStartedAt on the assistant node so the timeline timer has an anchor", async () => {
    useChatSessionStore.getState().ensureSession("s1");
    streamMock.mockReturnValue(scripted([startPacket("Hi"), endPacket()]));

    const before = Date.now();
    const { result } = renderHook(() => useChatController("s1"), { wrapper });
    await act(async () => {
      await result.current.submit("hi");
    });
    await waitFor(() => expect(result.current.chatState).toBe("input"));

    const [userNode, agentNode] = result.current.messages;
    expect(agentNode!.streamingStartedAt).toBeGreaterThanOrEqual(before);
    expect(agentNode!.streamingStartedAt).toBeLessThanOrEqual(Date.now());
    expect(userNode!.streamingStartedAt).toBeUndefined();
  });

  it("closes a user-stopped turn with a synthetic stop packet", async () => {
    useChatSessionStore.getState().ensureSession("s1");
    stopSessionMock.mockResolvedValue();
    // Ends only on abort, like the real one when its reader is cut — which is exactly why the
    // backend's own stop packet never arrives.
    streamMock.mockImplementation((_body, signal) =>
      (async function* () {
        yield idInfo;
        yield startPacket("Thinking");
        await new Promise<void>((resolve) => {
          if (signal.aborted) resolve();
          else signal.addEventListener("abort", () => resolve());
        });
      })(),
    );

    const { result } = renderHook(() => useChatController("s1"), { wrapper });
    await act(async () => {
      await result.current.submit("hi");
    });
    await act(async () => {
      result.current.stop();
    });
    await waitFor(() => expect(result.current.chatState).toBe("input"));

    // Without this the turn keeps looking like it is streaming until the session reloads.
    const agentNode = result.current.messages[1]!;
    const stopPacket = agentNode.packets.at(-1)!;
    expect(stopPacket.obj.type).toBe(PacketType.STOP);
    expect((stopPacket.obj as { stop_reason?: string }).stop_reason).toBe(
      StopReason.USER_CANCELLED,
    );
  });

  it("reloads the outcomes the server saved for a stopped response's requests", async () => {
    useChatSessionStore.getState().ensureSession("s1");
    stopSessionMock.mockResolvedValue();
    const agentRequest = {
      placement: { turn_index: 0 },
      obj: {
        ...(approvalRequest as { obj: object }).obj,
        approval_id: "a2",
        agent_name: "Researcher",
      },
    } as StreamEvent;
    streamMock.mockImplementation((_body, signal) =>
      (async function* () {
        yield idInfo;
        yield approvalRequest;
        yield agentRequest;
        await new Promise<void>((resolve) => {
          if (signal.aborted) resolve();
          else signal.addEventListener("abort", () => resolve());
        });
      })(),
    );
    // Stop rejects the root agent's request; the subagent's request still waits.
    getSessionMock.mockResolvedValue(
      savedTurn([
        approvalRequest,
        agentRequest,
        {
          placement: { turn_index: 0 },
          obj: {
            type: PacketType.TOOL_APPROVAL_RESOLVED,
            approval_id: "a1",
            outcome: "rejected",
          },
        },
        {
          placement: { turn_index: 0 },
          obj: {
            type: PacketType.STOP,
            stop_reason: StopReason.USER_CANCELLED,
          },
        },
      ]),
    );

    const { result } = renderHook(() => useChatController("s1"), { wrapper });
    await act(async () => {
      await result.current.submit("hi");
    });
    await waitFor(() =>
      expect(result.current.messages[1]?.packets.length).toBeGreaterThan(0),
    );
    await act(async () => {
      result.current.stop();
    });

    await waitFor(() => expect(getSessionMock).toHaveBeenCalledWith("s1"));
    await waitFor(() => expect(result.current.chatState).toBe("input"));
    expect(waitingIds()).toEqual(["a2"]);
    expect(useToolApprovalUi.getState().localStatuses.size).toBe(0);
  });

  it("keeps a waiting request decidable when the server Stop fails", async () => {
    useChatSessionStore.getState().ensureSession("s1");
    stopSessionMock.mockRejectedValueOnce(new Error("offline"));
    streamMock.mockImplementation((_body, signal) =>
      (async function* () {
        yield idInfo;
        yield approvalRequest;
        await new Promise<void>((resolve) => {
          if (signal.aborted) resolve();
          else signal.addEventListener("abort", () => resolve());
        });
      })(),
    );

    const { result } = renderHook(() => useChatController("s1"), { wrapper });
    await act(async () => {
      await result.current.submit("hi");
    });
    await waitFor(() =>
      expect(result.current.messages[1]?.packets.length).toBeGreaterThan(0),
    );
    const controller = useChatSessionStore
      .getState()
      .sessions.get("s1")?.abortController;
    await act(async () => {
      result.current.stop();
    });
    await waitFor(() =>
      expect(
        useChatSessionStore.getState().sessions.get("s1")?.stopRequested,
      ).toBe(false),
    );

    expect(stopSessionMock).toHaveBeenCalledWith("s1", 11);
    expect(controller?.signal.aborted).toBe(false);
    expect(result.current.chatState).toBe("streaming");
    expect(waitingIds()).toEqual(["a1"]);
    expect(useToolApprovalUi.getState().localStatuses.size).toBe(0);
    expect(toast.error).toHaveBeenCalledWith(
      "Could not stop the response. Try again.",
    );
    controller?.abort();
    await waitFor(() => expect(result.current.chatState).toBe("input"));
  });

  it("does not append a synthetic stop to a turn that ended on its own", async () => {
    useChatSessionStore.getState().ensureSession("s1");
    streamMock.mockReturnValue(scripted([startPacket("Hi"), endPacket()]));

    const { result } = renderHook(() => useChatController("s1"), { wrapper });
    await act(async () => {
      await result.current.submit("hi");
    });
    await waitFor(() => expect(result.current.chatState).toBe("input"));

    expect(
      result.current.messages[1]!.packets.some(
        (p) => p.obj.type === PacketType.STOP,
      ),
    ).toBe(false);
  });

  it("surfaces a mid-stream backend error as an error node (no stuck placeholder)", async () => {
    useChatSessionStore.getState().ensureSession("s1");
    streamMock.mockReturnValue(
      scripted([
        idInfo,
        startPacket("Partial "),
        streamError("The model exploded.", "RATE_LIMIT"),
      ]),
    );

    const { result } = renderHook(() => useChatController("s1"), { wrapper });
    await act(async () => {
      await result.current.submit("hi");
    });

    await waitFor(() => expect(result.current.chatState).toBe("input"));

    const messages = result.current.messages;
    expect(messages.map((m) => m.type)).toEqual(["user", "error"]);
    expect(messages[1]!.message).toBe("The model exploded.");
    expect(messages[1]!.errorCode).toBe("RATE_LIMIT");
    // The partial answer stays with the error.
    expect(accumulated(messages[1]!.packets)).toBe("Partial ");
  });

  it.each(["error packet", "HTTP 400"] as const)(
    "drops a send the server rejects before saving (%s)",
    async (kind) => {
      let now = Date.now();
      const clock = jest
        .spyOn(Date, "now")
        .mockImplementation(() => (now += 10));
      useChatSessionStore.getState().ensureSession("s1");
      streamMock
        .mockReturnValueOnce(
          scripted([idInfo, startPacket("Hi"), endPacket(), stopPacket()]),
        )
        .mockReturnValueOnce(
          kind === "error packet"
            ? scripted([streamError("Rejected.")])
            : (async function* (): AsyncGenerator<StreamEvent> {
                throw new StreamHttpError("Rejected.", 400);
              })(),
        )
        .mockReturnValueOnce(
          scripted([
            { user_message_id: 12, reserved_assistant_message_id: 13 },
            endPacket(),
            stopPacket(),
          ] as StreamEvent[]),
        );
      const onAccepted = jest.fn();

      const { result } = renderHook(() => useChatController("s1"), {
        wrapper,
      });
      await act(async () => {
        await result.current.submit("Question");
      });
      await waitFor(() => expect(result.current.chatState).toBe("input"));
      const treeBefore = useChatSessionStore
        .getState()
        .sessions.get("s1")!.messageTree;
      await act(async () => {
        await result.current.submit("Rejected question", [], onAccepted);
      });
      await waitFor(() => expect(result.current.chatState).toBe("input"));

      expect(
        useChatSessionStore.getState().sessions.get("s1")!.messageTree,
      ).toEqual(treeBefore);
      expect(toast.error).toHaveBeenCalledWith("Rejected.");
      // The composer keeps the draft until the server accepts a send.
      expect(onAccepted).not.toHaveBeenCalled();

      await act(async () => {
        await result.current.submit("Next");
      });
      await waitFor(() => expect(result.current.chatState).toBe("input"));
      expect(
        (
          streamMock.mock.calls[2]![0] as unknown as {
            parent_message_id: number | null;
          }
        ).parent_message_id,
      ).toBe(11);
      expect(result.current.messages.map((m) => m.messageId)).toEqual([
        10, 11, 12, 13,
      ]);
      clock.mockRestore();
    },
  );

  it("continues the conversation after a failed turn", async () => {
    // Node ids come from the clock; keep the two turns' ids distinct.
    let now = Date.now();
    const clock = jest.spyOn(Date, "now").mockImplementation(() => (now += 10));
    useChatSessionStore.getState().ensureSession("s1");
    streamMock
      .mockReturnValueOnce(
        scripted([idInfo, startPacket("Partial "), streamError("Boom.")]),
      )
      .mockReturnValueOnce(
        scripted([
          { user_message_id: 12, reserved_assistant_message_id: 13 },
          startPacket("Done"),
          endPacket(),
          stopPacket(),
        ] as StreamEvent[]),
      );

    const { result } = renderHook(() => useChatController("s1"), { wrapper });
    await act(async () => {
      await result.current.submit("Question");
    });
    await waitFor(() => expect(result.current.chatState).toBe("input"));
    await act(async () => {
      await result.current.submit("try again");
    });
    await waitFor(() => expect(result.current.chatState).toBe("input"));

    expect(
      (
        streamMock.mock.calls[1]![0] as unknown as {
          parent_message_id: number | null;
        }
      ).parent_message_id,
    ).toBe(11);
    const messages = result.current.messages;
    expect(messages.map((m) => [m.type, m.messageId])).toEqual([
      ["user", 10],
      ["error", 11],
      ["user", 12],
      ["assistant", 13],
    ]);
    clock.mockRestore();
  });

  it("does not auto-name a new session whose first run errors", async () => {
    createSessionMock.mockResolvedValue("err-session");
    streamMock.mockReturnValue(scripted([streamError("nope")]));

    const { result } = renderHook(() => useChatController(null), { wrapper });
    await act(async () => {
      await result.current.submit("first message");
    });

    await waitFor(() =>
      expect(
        useChatSessionStore.getState().sessions.get("err-session")?.chatState,
      ).toBe("input"),
    );
    // Give any stray naming timer a chance to fire before asserting it never did.
    await new Promise((resolve) => setTimeout(resolve, 250));
    expect(renameSessionMock).not.toHaveBeenCalled();
  });

  it("threads attachment descriptors into the send body and the optimistic user node", async () => {
    useChatSessionStore.getState().ensureSession("s1");
    streamMock.mockReturnValue(scripted([startPacket("Hi"), endPacket()]));

    const files: FileDescriptor[] = [
      {
        id: "blob-1",
        type: ChatFileType.IMAGE,
        name: "pic.png",
        user_file_id: "u1",
      },
    ];

    const { result } = renderHook(() => useChatController("s1"), { wrapper });
    await act(async () => {
      await result.current.submit("look at this", files);
    });

    await waitFor(() => expect(result.current.chatState).toBe("input"));

    const body = streamMock.mock.calls[0]![0] as unknown as {
      file_descriptors: FileDescriptor[];
    };
    expect(body.file_descriptors).toEqual(files);
    expect(result.current.messages[0]!.files).toEqual(files);
  });

  it.each([false, true])(
    "threads valid toolOptions onto the send body (deep research: %s)",
    async (deepResearch) => {
      useChatSessionStore.getState().ensureSession("s-tools");
      streamMock.mockReturnValue(scripted([startPacket("Hi"), endPacket()]));

      const { result } = renderHook(() => useChatController("s-tools"), {
        wrapper,
      });
      await act(async () => {
        await result.current.submit("hi", [], undefined, {
          deepResearch,
          allowed: [
            { type: "capability", tool_id: 1 },
            { type: "plugin", plugin_id: "p1" },
          ],
          preferredToolId: deepResearch ? null : 3,
          internalSearchFilters: { source_type: ["web"] },
          llmOverride: {
            model_configuration_id: 7,
            model_provider: "OpenAI Prod",
            model_version: "gpt-6-sol",
          },
        });
      });

      await waitFor(() => expect(result.current.chatState).toBe("input"));

      const body = streamMock.mock.calls[0]![0] as unknown as Record<
        string,
        unknown
      > & {
        deep_research: boolean;
        tool_options: unknown;
        llm_override: { model_configuration_id: number } | null;
      };
      expect(body.deep_research).toBe(deepResearch);
      expect(body.tool_options).toEqual({
        allowed: [
          { type: "capability", tool_id: 1 },
          { type: "plugin", plugin_id: "p1" },
        ],
        preferred: deepResearch ? null : { type: "capability", tool_id: 3 },
        internal_search_filters: { source_type: ["web"] },
      });
      expect(body).not.toHaveProperty("allowed_tool_ids");
      expect(body).not.toHaveProperty("preferred_tool_id");
      expect(body.llm_override).toEqual({
        model_configuration_id: 7,
        model_provider: "OpenAI Prod",
        model_version: "gpt-6-sol",
      });
    },
  );

  it("defaults the tool fields when no toolOptions are passed (backwards compatible)", async () => {
    useChatSessionStore.getState().ensureSession("s-defaults");
    streamMock.mockReturnValue(scripted([startPacket("Hi"), endPacket()]));

    const { result } = renderHook(() => useChatController("s-defaults"), {
      wrapper,
    });
    await act(async () => {
      await result.current.submit("hi");
    });

    await waitFor(() => expect(result.current.chatState).toBe("input"));

    const body = streamMock.mock.calls[0]![0] as unknown as {
      deep_research: boolean;
      tool_options: unknown;
      llm_override: unknown;
    };
    expect(body.deep_research).toBe(false);
    expect(body.tool_options).toEqual({
      allowed: null,
      preferred: null,
      internal_search_filters: null,
    });
    // Null, not omitted: the backend then runs the agent's own default model.
    expect(body.llm_override).toBeNull();
  });

  it("creates a session on the first message of a new chat", async () => {
    createSessionMock.mockResolvedValue("new-session");
    streamMock.mockReturnValue(scripted([startPacket("Hi"), endPacket()]));

    const { result } = renderHook(() => useChatController(null), { wrapper });
    await act(async () => {
      await result.current.submit("first message");
    });

    expect(createSessionMock).toHaveBeenCalledTimes(1);
    await waitFor(() =>
      expect(useChatSessionStore.getState().sessions.has("new-session")).toBe(
        true,
      ),
    );
    // Settle the fire-and-forget auto-name timer within the test.
    await waitFor(() => expect(renameSessionMock).toHaveBeenCalled());
  });

  it("keeps the draft (onAccepted not fired) if createChatSession fails", async () => {
    createSessionMock.mockRejectedValue(new Error("offline"));
    const onAccepted = jest.fn();

    const { result } = renderHook(() => useChatController(null), { wrapper });
    await act(async () => {
      try {
        await result.current.submit("unsent text", [], onAccepted);
      } catch {
        // create rejected; production drops the promise (fire-and-forget)
      }
    });

    expect(createSessionMock).toHaveBeenCalledTimes(1);
    expect(onAccepted).not.toHaveBeenCalled();
    expect(streamMock).not.toHaveBeenCalled();
  });

  // The chat surface stays mounted on other screens, where no chat is open.
  it("leaves no chat open when the surface shows no chat", () => {
    const view = renderHook(
      ({ id }: { id: string | null }) => useChatController(id),
      { wrapper, initialProps: { id: "s1" as string | null } },
    );
    expect(useChatSessionStore.getState().currentSessionId).toBe("s1");

    view.rerender({ id: null });

    expect(useChatSessionStore.getState().currentSessionId).toBeNull();
  });

  it("auto-names a new session once its first answer completes", async () => {
    createSessionMock.mockResolvedValue("new-session");
    streamMock.mockReturnValue(scripted([startPacket("Hi"), endPacket()]));

    const { result } = renderHook(() => useChatController(null), { wrapper });
    await act(async () => {
      await result.current.submit("first message");
    });

    await waitFor(() =>
      expect(renameSessionMock).toHaveBeenCalledWith("new-session"),
    );
    expect(renameSessionMock).toHaveBeenCalledTimes(1);
  });

  // A created chat has the empty approvals baseline; an agent that already asked reloads it.
  it("auto-names a new session whose first status read reloads it", async () => {
    createSessionMock.mockResolvedValue("new-session");
    streamMock.mockReturnValue(scripted([startPacket("Hi"), endPacket()]));
    jest
      .mocked(getChatSessionStatus)
      .mockResolvedValue({ is_processing: false, approvals_version: "v1" });
    getSessionMock.mockResolvedValue({
      ...savedTurn([]),
      approvals_version: "v1",
    });

    const { result } = renderHook(() => useChatController(null), { wrapper });
    await act(async () => {
      await result.current.submit("first message");
    });

    await waitFor(() =>
      expect(renameSessionMock).toHaveBeenCalledWith("new-session"),
    );
  });

  // The server reports "" while the chat has no approval request.
  it("keeps the streamed answer of a new chat with no approval request", async () => {
    createSessionMock.mockResolvedValue("new-session");
    streamMock.mockReturnValue(scripted([startPacket("Hi"), endPacket()]));
    jest
      .mocked(getChatSessionStatus)
      .mockResolvedValue({ is_processing: false, approvals_version: "" });

    const { result } = renderHook(() => useChatController(null), { wrapper });
    await act(async () => {
      await result.current.submit("first message");
    });

    await waitFor(() =>
      expect(
        useChatSessionStore.getState().sessions.get("new-session")?.chatState,
      ).toBe("input"),
    );
    await waitFor(() =>
      expect(renameSessionMock).toHaveBeenCalledWith("new-session"),
    );
    expect(getSessionMock).not.toHaveBeenCalled();
  });

  it("does not auto-name a continued (existing) session", async () => {
    useChatSessionStore.getState().ensureSession("s1");
    streamMock.mockReturnValue(scripted([startPacket("Hi"), endPacket()]));

    const { result } = renderHook(() => useChatController("s1"), { wrapper });
    await act(async () => {
      await result.current.submit("another message");
    });

    await waitFor(() => expect(result.current.chatState).toBe("input"));
    // Give any stray naming timer a chance to fire before asserting it never did.
    await new Promise((resolve) => setTimeout(resolve, 250));
    expect(renameSessionMock).not.toHaveBeenCalled();
  });

  it("does not auto-name when the first run is stopped", async () => {
    createSessionMock.mockResolvedValue("new-session");
    streamMock.mockImplementation((_body, signal) =>
      (async function* () {
        yield startPacket("Hello");
        while (!signal.aborted) {
          await new Promise((resolve) => setTimeout(resolve, 5));
          yield deltaPacket(".");
        }
      })(),
    );

    // Hook stays null-bound; after create the store owns the new session, so drive and inspect it there.
    const { result } = renderHook(() => useChatController(null), { wrapper });
    await act(async () => {
      await result.current.submit("first message");
    });
    await waitFor(() =>
      expect(
        useChatSessionStore.getState().sessions.get("new-session")?.chatState,
      ).toBe("streaming"),
    );

    act(() => useChatSessionStore.getState().abortSession("new-session"));

    await waitFor(() =>
      expect(
        useChatSessionStore.getState().sessions.get("new-session")?.chatState,
      ).toBe("input"),
    );
    await new Promise((resolve) => setTimeout(resolve, 250));
    expect(renameSessionMock).not.toHaveBeenCalled();
  });

  it("creates the new session with the selected persona id", async () => {
    createSessionMock.mockResolvedValue("s-agent");
    streamMock.mockReturnValue(scripted([startPacket("Hi"), endPacket()]));

    const { result } = renderHook(() => useChatController(null, 42), {
      wrapper,
    });
    await act(async () => {
      await result.current.submit("hello");
    });

    expect(createSessionMock).toHaveBeenCalledWith(42, null);
  });

  it("sends a starter-prompt override without using the composer input", async () => {
    createSessionMock.mockResolvedValue("s-starter");
    streamMock.mockReturnValue(scripted([startPacket("Hi"), endPacket()]));

    const { result } = renderHook(() => useChatController(null, 7), {
      wrapper,
    });
    // No setInput — the text comes from the override argument (a tapped starter).
    await act(async () => {
      await result.current.submit("Summarize my day");
    });

    expect(createSessionMock).toHaveBeenCalledWith(7, null);
    await waitFor(() =>
      expect(useChatSessionStore.getState().sessions.has("s-starter")).toBe(
        true,
      ),
    );
    const tree = useChatSessionStore
      .getState()
      .sessions.get("s-starter")!.messageTree;
    const userNode = [...tree.values()].find((node) => node.type === "user");
    expect(userNode?.message).toBe("Summarize my day");
  });

  it("guards a rapid double starter-tap on a new chat to a single session", async () => {
    let resolveCreate: ((id: string) => void) | undefined;
    createSessionMock.mockImplementation(
      () =>
        new Promise<string>((resolve) => {
          resolveCreate = resolve;
        }),
    );
    streamMock.mockReturnValue(scripted([startPacket("Hi"), endPacket()]));

    const { result } = renderHook(() => useChatController(null, 5), {
      wrapper,
    });

    await act(async () => {
      // Two synchronous taps before the first create resolves — the second must be blocked.
      void result.current.submit("first starter");
      void result.current.submit("second starter");
      resolveCreate?.("s-only");
    });

    expect(createSessionMock).toHaveBeenCalledTimes(1);
  });

  it("scopes a new chat to a project and pushes (Back returns to the project)", async () => {
    createSessionMock.mockResolvedValue("proj-session");
    streamMock.mockReturnValue(scripted([startPacket("Hi"), endPacket()]));

    const { result } = renderHook(() => useChatController(null, undefined, 7), {
      wrapper,
    });
    await act(async () => {
      await result.current.submit("scoped message");
    });

    expect(createSessionMock).toHaveBeenCalledWith(0, 7);
    expect(router.navigate).toHaveBeenCalledWith({
      pathname: "/chat/[id]",
      params: { id: "proj-session" },
    });
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("reports a new session via onSessionCreated instead of navigating", async () => {
    createSessionMock.mockResolvedValue("inline-session");
    streamMock.mockReturnValue(scripted([startPacket("Hi"), endPacket()]));
    const onCreated = jest.fn();

    const { result } = renderHook(
      () => useChatController(null, undefined, 7, onCreated),
      { wrapper },
    );
    await act(async () => {
      await result.current.submit("scoped message");
    });

    expect(onCreated).toHaveBeenCalledWith("inline-session");
    expect(router.navigate).not.toHaveBeenCalled();
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("stop aborts the stream and stops the backend stream by ID", async () => {
    useChatSessionStore.getState().ensureSession("s1");
    stopSessionMock.mockResolvedValue();
    streamMock.mockImplementation((_body, signal) =>
      (async function* () {
        yield idInfo;
        yield startPacket("Hello");
        while (!signal.aborted) {
          await new Promise((resolve) => setTimeout(resolve, 5));
          yield deltaPacket(".");
        }
      })(),
    );

    const { result } = renderHook(() => useChatController("s1"), { wrapper });
    await act(async () => {
      await result.current.submit("hi");
    });
    await waitFor(() => expect(result.current.chatState).toBe("streaming"));

    act(() => result.current.stop());

    await waitFor(() => expect(result.current.chatState).toBe("input"));
    expect(stopSessionMock).toHaveBeenCalledWith("s1", 11);
  });

  it.each([false, true])(
    "retries a failed scoped Stop (requested before acknowledgement: %s)",
    async (beforeAcknowledgement) => {
      useChatSessionStore.getState().ensureSession("s1");
      const acknowledgement = Promise.withResolvers<void>();
      const status = Promise.withResolvers<{ is_processing: boolean }>();
      jest
        .mocked(getChatSessionStatus)
        .mockResolvedValueOnce({ is_processing: false })
        .mockReturnValueOnce(status.promise);
      stopSessionMock
        .mockRejectedValueOnce(new Error("offline"))
        .mockResolvedValueOnce();
      streamMock.mockImplementation((_body, signal) =>
        (async function* () {
          await acknowledgement.promise;
          yield idInfo;
          if (!signal.aborted) {
            await new Promise<void>((resolve) =>
              signal.addEventListener("abort", () => resolve(), { once: true }),
            );
          }
        })(),
      );
      const { result } = renderHook(() => useChatController("s1"), { wrapper });
      await act(async () => {
        await result.current.submit("hi");
      });
      if (beforeAcknowledgement) act(() => result.current.stop());
      await act(async () => {
        acknowledgement.resolve();
      });
      if (!beforeAcknowledgement) act(() => result.current.stop());
      await waitFor(() => {
        expect(stopSessionMock).toHaveBeenCalledTimes(1);
        expect(
          useChatSessionStore.getState().sessions.get("s1")?.stopRequested,
        ).toBe(false);
      });
      act(() => result.current.stop());
      await waitFor(() => expect(stopSessionMock).toHaveBeenCalledTimes(2));
      expect(stopSessionMock).toHaveBeenLastCalledWith("s1", 11);
      await act(async () => {
        status.resolve({ is_processing: false });
      });
      await waitFor(() => expect(result.current.chatState).toBe("input"));
    },
  );

  it("reports session creation before navigation and acceptance only after acknowledgement", async () => {
    createSessionMock.mockResolvedValue("new-session");
    const acknowledgement = Promise.withResolvers<void>();
    const accepted = jest.fn();
    const created = jest.fn(() => {
      expect(router.replace).not.toHaveBeenCalled();
    });
    streamMock.mockImplementation(() =>
      (async function* () {
        await acknowledgement.promise;
        yield idInfo;
      })(),
    );
    const { result } = renderHook(() => useChatController(null), { wrapper });
    await act(async () => {
      await result.current.submit("hi", [], accepted, undefined, created);
    });
    expect(created).toHaveBeenCalledTimes(1);
    expect(router.replace).toHaveBeenCalledTimes(1);
    expect(accepted).not.toHaveBeenCalled();
    await act(async () => {
      acknowledgement.resolve();
    });
    await waitFor(() => expect(accepted).toHaveBeenCalledTimes(1));
  });

  it("holds ownership while the server saves and blocks a repeat send", async () => {
    useChatSessionStore.getState().ensureSession("s1");
    let resolveStatus!: (value: { is_processing: boolean }) => void;
    jest
      .mocked(getChatSessionStatus)
      .mockResolvedValueOnce({ is_processing: false })
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveStatus = resolve;
          }),
      );
    streamMock.mockReturnValue(
      scripted([idInfo, startPacket("saved later"), stopPacket()]),
    );
    const { result } = renderHook(() => useChatController("s1"), { wrapper });
    await act(async () => {
      await result.current.submit("hi");
    });
    await waitFor(() => expect(result.current.chatState).toBe("settling"));
    const owner = useChatSessionStore
      .getState()
      .sessions.get("s1")?.abortController;
    expect(owner).not.toBeNull();
    await act(async () => {
      await result.current.submit("again");
    });
    expect(streamMock).toHaveBeenCalledTimes(1);
    await act(async () => {
      resolveStatus({ is_processing: false });
    });
    await waitFor(() => expect(result.current.chatState).toBe("input"));
  });

  it("does not clear a draft when readiness cannot be confirmed", async () => {
    useChatSessionStore.getState().ensureSession("s1");
    jest
      .mocked(getChatSessionStatus)
      .mockRejectedValueOnce(new Error("offline"));
    const accepted = jest.fn();
    const { result } = renderHook(() => useChatController("s1"), { wrapper });
    await act(async () => {
      await result.current.submit("retry me", [], accepted);
    });
    expect(accepted).not.toHaveBeenCalled();
    expect(streamMock).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalledWith(
      "Could not confirm this conversation is ready. Try again.",
    );
  });

  it("explains a busy session without accepting the draft", async () => {
    useChatSessionStore.getState().ensureSession("s1");
    jest
      .mocked(getChatSessionStatus)
      .mockResolvedValueOnce({ is_processing: true });
    const accepted = jest.fn();
    const { result } = renderHook(() => useChatController("s1"), { wrapper });
    await act(async () => {
      await result.current.submit("retry me", [], accepted);
    });
    expect(accepted).not.toHaveBeenCalled();
    expect(streamMock).not.toHaveBeenCalled();
    expect(toast.info).toHaveBeenCalledWith(
      "This conversation is still processing. Try again shortly.",
    );
  });

  it("waits for acknowledgement before sending scoped Stop", async () => {
    useChatSessionStore.getState().ensureSession("s1");
    let acknowledge!: () => void;
    const ready = new Promise<void>((resolve) => {
      acknowledge = resolve;
    });
    streamMock.mockImplementation((_body, signal) =>
      (async function* () {
        await ready;
        yield idInfo;
        if (!signal.aborted) yield startPacket("late");
      })(),
    );
    const { result } = renderHook(() => useChatController("s1"), { wrapper });
    await act(async () => {
      await result.current.submit("hi");
    });
    act(() => result.current.stop());
    expect(stopSessionMock).not.toHaveBeenCalled();
    expect(
      useChatSessionStore.getState().sessions.get("s1")?.abortController?.signal
        .aborted,
    ).toBe(false);
    await act(async () => {
      acknowledge();
    });
    await waitFor(() => expect(result.current.chatState).toBe("input"));
    expect(stopSessionMock).toHaveBeenCalledWith("s1", 11);
  });

  it("keeps following after a late acknowledgement and a failed scoped Stop", async () => {
    jest.useFakeTimers();
    try {
      useChatSessionStore.getState().ensureSession("s1");
      const acknowledgement = Promise.withResolvers<void>();
      stopSessionMock.mockRejectedValueOnce(new Error("offline"));
      streamMock.mockImplementation((_body, signal) =>
        (async function* (): AsyncGenerator<StreamEvent> {
          await acknowledgement.promise;
          yield idInfo;
          yield approvalRequest;
          await new Promise<void>((resolve) =>
            signal.addEventListener("abort", () => resolve(), { once: true }),
          );
        })(),
      );
      const { result, unmount } = renderHook(() => useChatController("s1"), {
        wrapper,
      });
      await act(async () => {
        await result.current.submit("hi");
      });
      const controller = useChatSessionStore
        .getState()
        .sessions.get("s1")?.abortController;
      act(() => result.current.stop());
      await act(async () => {
        acknowledgement.resolve();
      });
      expect(stopSessionMock).toHaveBeenCalledWith("s1", 11);
      expect(
        useChatSessionStore.getState().sessions.get("s1")?.stopRequested,
      ).toBe(false);

      await act(async () => {
        jest.advanceTimersByTime(10_000);
      });

      expect(controller?.signal.aborted).toBe(false);
      expect(waitingIds()).toEqual(["a1"]);
      controller?.abort();
      unmount();
    } finally {
      jest.useRealTimers();
    }
  });

  it("stops waiting for a missing acknowledgement without sending an unscoped Stop", async () => {
    jest.useFakeTimers();
    try {
      useChatSessionStore.getState().ensureSession("s1");
      const status = Promise.withResolvers<{ is_processing: boolean }>();
      jest
        .mocked(getChatSessionStatus)
        .mockResolvedValueOnce({ is_processing: false })
        .mockReturnValueOnce(status.promise);
      streamMock.mockImplementation((_body, signal) =>
        (async function* (): AsyncGenerator<StreamEvent> {
          await new Promise<void>((resolve) =>
            signal.addEventListener("abort", () => resolve(), { once: true }),
          );
        })(),
      );
      const { result, unmount } = renderHook(() => useChatController("s1"), {
        wrapper,
      });
      await act(async () => {
        await result.current.submit("hi");
      });
      act(() => result.current.stop());
      await act(async () => {
        jest.advanceTimersByTime(10_000);
      });
      expect(stopSessionMock).not.toHaveBeenCalled();
      expect(result.current.chatState).toBe("settling");
      await act(async () => {
        await result.current.submit("too soon");
      });
      expect(streamMock).toHaveBeenCalledTimes(1);
      await act(async () => {
        status.resolve({ is_processing: false });
      });
      expect(result.current.chatState).toBe("input");
      unmount();
    } finally {
      jest.useRealTimers();
    }
  });

  it("releases its controller without claiming idle when readiness returns a permanent error", async () => {
    useChatSessionStore.getState().ensureSession("s1");
    jest
      .mocked(getChatSessionStatus)
      .mockResolvedValueOnce({ is_processing: false })
      .mockRejectedValueOnce(
        new ApiError({ status: 403, detail: "Access denied" }),
      );
    streamMock.mockReturnValue(scripted([idInfo]));
    const { result } = renderHook(() => useChatController("s1"), { wrapper });
    await act(async () => {
      await result.current.submit("hi");
    });
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Access denied"),
    );
    expect(result.current.chatState).toBe("unconfirmed");
    expect(
      useChatSessionStore.getState().sessions.get("s1")?.abortController,
    ).toBeNull();
    expect(getChatSessionStatus).toHaveBeenCalledTimes(2);
  });

  it("does not release a newer owner after an old readiness check", async () => {
    useChatSessionStore.getState().ensureSession("s1");
    let resolveStatus!: (value: { is_processing: boolean }) => void;
    jest
      .mocked(getChatSessionStatus)
      .mockResolvedValueOnce({ is_processing: false })
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveStatus = resolve;
          }),
      );
    streamMock.mockReturnValue(scripted([idInfo]));
    const { result } = renderHook(() => useChatController("s1"), { wrapper });
    await act(async () => {
      await result.current.submit("hi");
    });
    await waitFor(() => expect(result.current.chatState).toBe("settling"));
    const newer = new AbortController();
    await act(async () => {
      useChatSessionStore.getState().setAbortController("s1", newer);
      useChatSessionStore.getState().updateChatState("s1", "loading");
      resolveStatus({ is_processing: false });
    });
    expect(
      useChatSessionStore.getState().sessions.get("s1")?.abortController,
    ).toBe(newer);
    expect(result.current.chatState).toBe("loading");
  });

  it("hydrates an opened session from the backend snapshot", async () => {
    getSessionMock.mockResolvedValue({
      chat_session_id: "s2",
      description: "",
      persona_id: 0,
      messages: [
        {
          message_id: 1,
          message_type: "user",
          parent_message: null,
          latest_child_message: 2,
          message: "hi there",
          files: [],
          time_sent: "",
          error: null,
        },
        {
          message_id: 2,
          message_type: "assistant",
          parent_message: 1,
          latest_child_message: null,
          message: "answer",
          files: [],
          time_sent: "",
          error: null,
        },
      ],
      packets: [[startPacket("answer")]],
      time_created: "",
    });

    const { result } = renderHook(() => useChatController("s2"), { wrapper });

    await waitFor(() => expect(result.current.messages).toHaveLength(2));
    expect(result.current.messages.map((m) => m.type)).toEqual([
      "user",
      "assistant",
    ]);
    expect(result.current.messages[0]!.message).toBe("hi there");
    expect(getSessionMock).toHaveBeenCalledWith("s2");
  });

  it("reports the hydrated session's persona", async () => {
    // The sessions list omits project chats, so this is the only way the composer can learn which
    // agent a project chat runs on.
    getSessionMock.mockResolvedValue({
      chat_session_id: "s3",
      description: "",
      persona_id: 7,
      messages: [],
      packets: [],
      time_created: "",
    });

    const { result } = renderHook(() => useChatController("s3"), { wrapper });

    await waitFor(() => expect(result.current.conversationPersonaId).toBe(7));
  });

  it("has no conversation persona for a brand-new chat", () => {
    const { result } = renderHook(() => useChatController(null), { wrapper });
    expect(result.current.conversationPersonaId).toBeNull();
    expect(getSessionMock).not.toHaveBeenCalled();
  });

  describe("while a question waits", () => {
    const postAnswersMock = postQuestionAnswers as unknown as Mock<
      typeof postQuestionAnswers
    >;
    const questionRequest = {
      placement: { turn_index: 0 },
      obj: {
        type: PacketType.TOOL_QUESTION_REQUEST,
        question_request_id: "q1",
        tool_call_id: "c1",
        questions: [
          {
            id: "scope",
            header: "Scope",
            question: "Which scope?",
            options: [
              { label: "Small", description: "One file." },
              { label: "Large", description: "The whole app." },
            ],
          },
        ],
      },
    } as StreamEvent;
    const continuation = { stream_id: 40, response_ids: [11] };

    async function pausedOnQuestion() {
      useChatSessionStore.getState().ensureSession("s1");
      useChatSessionStore.setState({ currentSessionId: "s1" });
      streamMock.mockReturnValueOnce(
        scripted([idInfo, questionRequest, pausedStop]),
      );
      const rendered = renderHook(() => useChatController("s1"), { wrapper });
      await act(async () => {
        await rendered.result.current.submit("Question");
      });
      await waitFor(() =>
        expect(rendered.result.current.chatState).toBe("input"),
      );
      return rendered;
    }

    beforeEach(() => {
      useToolQuestionUi.setState({ localStatuses: new Map() });
    });

    it("sends the message as the answer and follows the continuation", async () => {
      const { result } = await pausedOnQuestion();
      expect(result.current.answersQuestions).toBe(true);
      postAnswersMock.mockResolvedValue({
        question_request_id: "q1",
        continuation,
      });
      const onAccepted = jest.fn();

      await act(async () => {
        await result.current.submit("  Small, please  ", [], onAccepted);
      });

      expect(postAnswersMock).toHaveBeenCalledWith("q1", {
        message: "Small, please",
      });
      expect(streamMock).toHaveBeenCalledTimes(1);
      expect(onAccepted).toHaveBeenCalled();
      expect(useToolQuestionUi.getState().localStatuses.get("q1")).toEqual({
        outcome: "answered",
        answered_via: "message",
        message: "Small, please",
      });
      expect(jest.mocked(followUserAnswer).mock.calls[0]?.slice(0, 2)).toEqual([
        "s1",
        continuation,
      ]);
      // The text shows in the response's record, not as a new turn.
      expect(result.current.messages.map((m) => m.message)).toEqual([
        "Question",
        "",
      ]);
    });

    it("keeps the draft when an approval of the response still waits", async () => {
      const { result } = await pausedOnQuestion();
      postAnswersMock.mockRejectedValue(
        new ApiError({ status: 409, code: "APPROVAL_PENDING" }),
      );
      const onAccepted = jest.fn();

      await act(async () => {
        await result.current.submit("Small", [], onAccepted);
      });

      expect(onAccepted).not.toHaveBeenCalled();
      expect(toast.warning).toHaveBeenCalledWith(
        "Approve or reject the pending tool calls first.",
      );
      expect(useToolQuestionUi.getState().localStatuses.has("q1")).toBe(false);
      expect(followUserAnswer).not.toHaveBeenCalled();
    });

    it("shows the server's reason when it refuses the answer", async () => {
      jest.spyOn(console, "warn").mockImplementation(() => {});
      const { result } = await pausedOnQuestion();
      postAnswersMock.mockRejectedValue(
        new ApiError({ status: 400, detail: "This message is not allowed." }),
      );
      const onAccepted = jest.fn();

      await act(async () => {
        await result.current.submit("Small", [], onAccepted);
      });

      expect(onAccepted).not.toHaveBeenCalled();
      expect(toast.error).toHaveBeenCalledWith("This message is not allowed.");
      expect(useToolQuestionUi.getState().localStatuses.has("q1")).toBe(false);
      expect(followUserAnswer).not.toHaveBeenCalled();
    });

    it("keeps the draft and reloads when the question no longer waits", async () => {
      const { result } = await pausedOnQuestion();
      postAnswersMock.mockRejectedValue(new ApiError({ status: 409 }));
      const onAccepted = jest.fn();

      await act(async () => {
        await result.current.submit("Small", [], onAccepted);
      });

      expect(onAccepted).not.toHaveBeenCalled();
      expect(
        useToolQuestionUi.getState().localStatuses.get("q1")?.outcome,
      ).toBe("cancelled");
      expect(jest.mocked(followUserAnswer).mock.calls[0]?.slice(0, 2)).toEqual([
        "s1",
        null,
      ]);
    });

    it("reloads how Stop ended a live response's question", async () => {
      useChatSessionStore.getState().ensureSession("s1");
      stopSessionMock.mockResolvedValue();
      streamMock.mockImplementation((_body, signal) =>
        (async function* () {
          yield idInfo;
          yield questionRequest;
          await new Promise<void>((resolve) => {
            if (signal.aborted) resolve();
            else signal.addEventListener("abort", () => resolve());
          });
        })(),
      );
      getSessionMock.mockResolvedValue(
        savedTurn([
          questionRequest,
          {
            placement: { turn_index: 0 },
            obj: {
              type: PacketType.TOOL_QUESTION_RESOLVED,
              question_request_id: "q1",
              outcome: "cancelled",
            },
          },
          {
            placement: { turn_index: 0 },
            obj: {
              type: PacketType.STOP,
              stop_reason: StopReason.USER_CANCELLED,
            },
          },
        ]),
      );

      const { result } = renderHook(() => useChatController("s1"), {
        wrapper,
      });
      await act(async () => {
        await result.current.submit("hi");
      });
      await waitFor(() =>
        expect(result.current.messages[1]?.packets.length).toBeGreaterThan(0),
      );
      await act(async () => {
        result.current.stop();
      });

      await waitFor(() => expect(getSessionMock).toHaveBeenCalledWith("s1"));
      await waitFor(() => expect(result.current.chatState).toBe("input"));
      expect(
        readToolQuestions(result.current.messages[1]?.packets ?? []).map(
          (entry) => entry.resolved?.outcome,
        ),
      ).toEqual(["cancelled"]);
    });

    it("does not send attachments as an answer", async () => {
      const { result } = await pausedOnQuestion();
      const onAccepted = jest.fn();

      await act(async () => {
        await result.current.submit(
          "Small",
          [{ id: "f1", type: ChatFileType.DOCUMENT, name: "a.txt" }],
          onAccepted,
        );
      });

      expect(postAnswersMock).not.toHaveBeenCalled();
      expect(streamMock).toHaveBeenCalledTimes(1);
      expect(onAccepted).not.toHaveBeenCalled();
      expect(toast.warning).toHaveBeenCalledWith(
        "Remove the attachments to answer the question.",
      );
    });
  });
});
