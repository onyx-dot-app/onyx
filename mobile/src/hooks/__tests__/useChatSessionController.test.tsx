import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  jest,
} from "@jest/globals";
import type { Mock } from "jest-mock";
import * as React from "react";
import { act, renderHook, waitFor } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ApiError } from "@/api/errors";
import { toast } from "@/hooks/useToast";
import { QUERY_KEYS } from "@/api/query-keys";
import { getChatSession, getChatSessionStatus } from "@/api/chat/sessions";
import {
  resumeChatMessage,
  StreamHttpError,
  type StreamEvent,
} from "@/api/chat/stream";
import { processRawChatHistory } from "@/chat/chatHistory";
import {
  BackendChatSession,
  BackendMessage,
  ChatStream,
} from "@/chat/interfaces";
import {
  getLatestMessageChain,
  getMessageByMessageId,
} from "@/chat/messageTree";
import { Packet, PacketType, StopReason } from "@/chat/streamingModels";
import {
  readToolApprovals,
  toolApprovalStatus,
  useToolApprovalUi,
} from "@/chat/toolApprovals";
import {
  recoverChatSession,
  useChatSessionController,
  watchBackgroundAgents,
} from "@/hooks/useChatSessionController";
import { useChatSessionStore } from "@/state/chatSessionStore";

const SERVER_URL = "https://example.test";

// `jest.mock` is hoisted above imports by babel-jest.
jest.mock("@/state/session", () => ({
  useSession: (selector: (s: { serverUrl: string | null }) => unknown) =>
    selector({ serverUrl: "https://example.test" }),
}));
// Status polls wait this long instead of the real interval, so tests do not sleep.
jest.mock("@/chat/constants", () => ({
  ...jest.requireActual<typeof import("@/chat/constants")>("@/chat/constants"),
  SESSION_POLL_INTERVAL_MS: 10,
}));
jest.mock("@/hooks/useToast", () => ({ toast: { error: jest.fn() } }));
jest.mock("@/api/chat/stream", () => ({
  resumeChatMessage: jest.fn(),
  isPacket: (event: { obj?: unknown; placement?: unknown }) =>
    "obj" in event && "placement" in event,
  isHeartbeat: (event: { obj?: { type?: string }; type?: string }) =>
    event?.obj?.type === "chat_heartbeat" || event?.type === "chat_heartbeat",
  isStreamCursor: (event: { next_cursor?: unknown }) => "next_cursor" in event,
  isStreamError: (event: { error?: unknown }) =>
    "error" in event && typeof event.error === "string",
  StreamHttpError: class StreamHttpError extends Error {
    status: number;
    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  },
}));
jest.mock("@/api/chat/sessions", () => ({
  getChatSession: jest.fn(),
  getChatSessionStatus: jest.fn(async () => ({ is_processing: false })),
}));

const resumeMock = resumeChatMessage as unknown as Mock<
  (
    id: string,
    streamId: number,
    cursor: number,
    signal: AbortSignal,
  ) => AsyncGenerator<StreamEvent>
>;
const getSessionMock = getChatSession as unknown as Mock<
  (id: string) => Promise<BackendChatSession>
>;

function startPacket(content: string): StreamEvent {
  return {
    placement: { turn_index: 0 },
    obj: { type: PacketType.MESSAGE_START, id: "m", content },
  } as StreamEvent;
}
function deltaPacket(content: string): StreamEvent {
  return {
    placement: { turn_index: 0 },
    obj: { type: PacketType.MESSAGE_DELTA, content },
  } as StreamEvent;
}
function endPacket(): StreamEvent {
  return {
    placement: { turn_index: 0 },
    obj: { type: PacketType.MESSAGE_END },
  } as StreamEvent;
}
// Ends a batch of resumed packets, as the server does after each read.
function cursor(nextCursor: number, replayComplete = true): StreamEvent {
  return {
    stream_id: 2,
    next_cursor: nextCursor,
    replay_complete: replayComplete,
  };
}
function stopPacket(): StreamEvent {
  return {
    placement: { turn_index: 0 },
    obj: { type: PacketType.STOP },
  } as StreamEvent;
}
function streamError(error: string, errorCode?: string): StreamEvent {
  return { error, error_code: errorCode ?? null } as unknown as StreamEvent;
}

// A persisted session snapshot's `packets` are typed as Packet[][] (not StreamEvent).
function historyPacket(content: string): Packet {
  return {
    placement: { turn_index: 0 },
    obj: { type: PacketType.MESSAGE_START, id: "m", content },
  } as unknown as Packet;
}

function backendMessages(assistantText: string): BackendMessage[] {
  return [
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
      message: assistantText,
      files: [],
      time_sent: "",
      error: null,
    },
  ];
}

// Assistant stream_id 2 is in flight — a hydrated session whose assistant node is still empty.
function seedLiveSession(currentRunId: number | null): void {
  useChatSessionStore
    .getState()
    .hydrateSession("s1", processRawChatHistory(backendMessages(""), [[]]));
  useChatSessionStore.setState({ currentSessionId: "s1" });
  const snapshot: BackendChatSession = {
    chat_session_id: "s1",
    description: "",
    persona_id: 0,
    messages: backendMessages(""),
    packets: [[]],
    time_created: "",
    current_stream:
      currentRunId == null
        ? null
        : { stream_id: currentRunId, response_ids: [currentRunId] },
  };
  client.setQueryData(QUERY_KEYS.chatSession(SERVER_URL, "s1"), snapshot);
}

function assistantText(sessionId: string, messageId: number): string {
  const tree = useChatSessionStore
    .getState()
    .sessions.get(sessionId)?.messageTree;
  const node = tree ? getMessageByMessageId(tree, messageId) : undefined;
  return (node?.packets ?? [])
    .filter(
      (p) =>
        p.obj.type === PacketType.MESSAGE_START ||
        p.obj.type === PacketType.MESSAGE_DELTA,
    )
    .map((p) => (p.obj as { content?: string }).content ?? "")
    .join("");
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

let client: QueryClient;
function wrapper({ children }: { children: React.ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useChatSessionController", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    jest
      .mocked(getChatSessionStatus)
      .mockResolvedValue({ is_processing: false });
    client = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
    });
    useChatSessionStore.setState({
      currentSessionId: null,
      sessions: new Map(),
    });
  });

  it.each([2, null])(
    "retries failed history loading on reopen with stream ID %s",
    async (streamId) => {
      seedLiveSession(streamId);
      useChatSessionStore.getState().updateChatState("s1", "settling");
      resumeMock.mockImplementation(() =>
        scripted([startPacket("Live answer"), endPacket(), cursor(2)]),
      );
      getSessionMock.mockRejectedValueOnce(new Error("History unavailable"));
      const { rerender } = renderHook(
        ({ sessionId }: { sessionId: string | null }) =>
          useChatSessionController(sessionId),
        { initialProps: { sessionId: "s1" }, wrapper },
      );
      await waitFor(() =>
        expect(toast.error).toHaveBeenCalledWith(
          "Could not refresh saved messages. Reopen this conversation to retry.",
        ),
      );
      expect(useChatSessionStore.getState().sessions.get("s1")?.chatState).toBe(
        "unconfirmed",
      );
      if (streamId !== null) {
        expect(assistantText("s1", 2)).toBe("Live answer");
      }
      expect(
        useChatSessionStore.getState().sessions.get("s1")?.abortController,
      ).toBeNull();
      expect(getSessionMock).toHaveBeenCalledTimes(1);

      rerender({ sessionId: null });
      getSessionMock.mockResolvedValueOnce({
        chat_session_id: "s1",
        description: "",
        persona_id: 0,
        messages: backendMessages("Saved answer"),
        packets: [[historyPacket("Saved answer")]],
        time_created: "",
        current_stream: null,
      });
      rerender({ sessionId: "s1" });
      await waitFor(() =>
        expect(
          useChatSessionStore.getState().sessions.get("s1")?.chatState,
        ).toBe("input"),
      );
      expect(getSessionMock).toHaveBeenCalledTimes(2);
      expect(assistantText("s1", 2)).toBe("Saved answer");
    },
  );

  it("stops recovery when the session is unavailable without claiming it is idle", async () => {
    seedLiveSession(2);
    resumeMock.mockReturnValue(
      scripted([startPacket("Live answer"), endPacket()]),
    );
    jest
      .mocked(getChatSessionStatus)
      .mockRejectedValueOnce(
        new ApiError({ status: 404, detail: "Conversation unavailable" }),
      );
    renderHook(() => useChatSessionController("s1"), { wrapper });
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Conversation unavailable"),
    );
    expect(useChatSessionStore.getState().sessions.get("s1")?.chatState).toBe(
      "unconfirmed",
    );
    expect(
      useChatSessionStore.getState().sessions.get("s1")?.abortController,
    ).toBeNull();
    expect(getChatSessionStatus).toHaveBeenCalledTimes(1);
    expect(getSessionMock).not.toHaveBeenCalled();
  });

  it.each(["complete", null] as const)(
    "rechecks unresolved readiness on reopen with saved status %s and no current stream",
    async (savedStatus) => {
      seedLiveSession(null);
      useChatSessionStore.getState().setStreamId("s1", 2);
      useChatSessionStore
        .getState()
        .patchNode("s1", 2, { type: "error", message: "Original failure" });
      useChatSessionStore.getState().updateChatState("s1", "unconfirmed");
      jest
        .mocked(getChatSessionStatus)
        .mockRejectedValueOnce(
          new ApiError({ status: 403, detail: "Access denied" }),
        );
      const { rerender } = renderHook(
        ({ sessionId }: { sessionId: string | null }) =>
          useChatSessionController(sessionId),
        { initialProps: { sessionId: "s1" }, wrapper },
      );
      await waitFor(() =>
        expect(toast.error).toHaveBeenCalledWith("Access denied"),
      );
      expect(
        useChatSessionStore.getState().sessions.get("s1")?.abortController,
      ).toBeNull();
      expect(useChatSessionStore.getState().sessions.get("s1")?.chatState).toBe(
        "unconfirmed",
      );
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 30));
      });
      expect(getChatSessionStatus).toHaveBeenCalledTimes(1);
      expect(resumeMock).not.toHaveBeenCalled();

      rerender({ sessionId: null });
      getSessionMock.mockResolvedValueOnce({
        chat_session_id: "s1",
        description: "",
        persona_id: 0,
        messages: backendMessages("Saved answer").map((message) =>
          message.message_type === "assistant"
            ? { ...message, response_status: savedStatus }
            : message,
        ),
        packets: [[historyPacket("Saved answer")]],
        time_created: "",
        current_stream: null,
      });
      rerender({ sessionId: "s1" });
      await waitFor(() =>
        expect(
          useChatSessionStore.getState().sessions.get("s1")?.chatState,
        ).toBe("input"),
      );
      expect(getChatSessionStatus).toHaveBeenCalledTimes(2);
      expect(resumeMock).not.toHaveBeenCalled();
      const tree = useChatSessionStore
        .getState()
        .sessions.get("s1")!.messageTree;
      expect(getMessageByMessageId(tree, 2)).toMatchObject(
        savedStatus === "complete"
          ? { type: "assistant", message: "Saved answer" }
          : { type: "error", message: "Original failure" },
      );
    },
  );

  it.each([undefined, 2])(
    "preserves an unmatched failed question and response on reopen (message ID: %s)",
    async (messageId) => {
      seedLiveSession(null);
      useChatSessionStore.getState().patchNode("s1", 2, {
        messageId,
        type: "error",
        message: "Connection failed",
        errorCode: "STREAM_GAP",
      });
      useChatSessionStore.getState().updateChatState("s1", "unconfirmed");
      getSessionMock.mockResolvedValueOnce({
        chat_session_id: "s1",
        description: "",
        persona_id: 0,
        messages: [],
        packets: [],
        time_created: "",
        current_stream: null,
      });

      renderHook(() => useChatSessionController("s1"), { wrapper });

      await waitFor(() =>
        expect(
          useChatSessionStore.getState().sessions.get("s1")?.chatState,
        ).toBe("input"),
      );
      expect(resumeMock).not.toHaveBeenCalled();
      expect(getSessionMock).toHaveBeenCalledTimes(1);
      const tree = useChatSessionStore
        .getState()
        .sessions.get("s1")!.messageTree;
      expect(getLatestMessageChain(tree)).toEqual([
        expect.objectContaining({ type: "user", message: "hi there" }),
        expect.objectContaining({
          type: "error",
          message: "Connection failed",
          errorCode: "STREAM_GAP",
        }),
      ]);
    },
  );

  it("resumes an in-flight run then settles from the persisted session", async () => {
    seedLiveSession(2);
    resumeMock.mockReturnValue(
      scripted([startPacket("Answer"), deltaPacket(" done"), endPacket()]),
    );
    getSessionMock.mockResolvedValue({
      chat_session_id: "s1",
      description: "Named",
      persona_id: 0,
      messages: backendMessages("final answer"),
      packets: [[historyPacket("final answer")]],
      time_created: "",
      current_stream: null,
    });

    renderHook(() => useChatSessionController("s1"), { wrapper });

    expect(resumeMock).toHaveBeenCalledWith("s1", 2, 0, expect.anything());
    await waitFor(() => expect(getSessionMock).toHaveBeenCalledWith("s1"));
    await waitFor(() => expect(assistantText("s1", 2)).toBe("final answer"));
    await waitFor(() =>
      expect(useChatSessionStore.getState().sessions.get("s1")?.chatState).toBe(
        "input",
      ),
    );
  });

  it("resumes reactively when the snapshot arrives after mount", async () => {
    // Store hydrated, but the RQ cache is empty at mount (useChatController's fetch hasn't resolved).
    useChatSessionStore
      .getState()
      .hydrateSession("s1", processRawChatHistory(backendMessages(""), [[]]));
    useChatSessionStore.setState({ currentSessionId: "s1" });
    resumeMock.mockReturnValue(scripted([deltaPacket("late")]));
    getSessionMock.mockResolvedValue({
      chat_session_id: "s1",
      description: "Named",
      persona_id: 0,
      messages: backendMessages("late"),
      packets: [[historyPacket("late")]],
      time_created: "",
      current_stream: null,
    });

    renderHook(() => useChatSessionController("s1"), { wrapper });

    // No snapshot yet → nothing to resume.
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(resumeMock).not.toHaveBeenCalled();

    // The hydration fetch resolves: the observer sees current_stream and re-attaches.
    act(() => {
      client.setQueryData(QUERY_KEYS.chatSession(SERVER_URL, "s1"), {
        chat_session_id: "s1",
        description: "",
        persona_id: 0,
        messages: backendMessages(""),
        packets: [[]],
        time_created: "",
        current_stream: { stream_id: 2, response_ids: [2] },
      });
    });

    await waitFor(() =>
      expect(resumeMock).toHaveBeenCalledWith("s1", 2, 0, expect.anything()),
    );
  });

  it("streams replayed packets into the assistant node while tailing", async () => {
    seedLiveSession(2);
    let releaseTail: () => void = () => {};
    const tail = new Promise<void>((resolve) => {
      releaseTail = resolve;
    });
    resumeMock.mockReturnValue(
      (async function* () {
        yield startPacket("Hel");
        yield deltaPacket("lo");
        yield cursor(2);
        await tail;
        yield endPacket();
        yield stopPacket();
        yield cursor(4);
      })(),
    );
    getSessionMock.mockResolvedValue({
      chat_session_id: "s1",
      description: "Named",
      persona_id: 0,
      messages: backendMessages("Hello"),
      packets: [[historyPacket("Hello")]],
      time_created: "",
      current_stream: null,
    });

    renderHook(() => useChatSessionController("s1"), { wrapper });

    // Packets render live, before the run ends / settle runs.
    await waitFor(() => expect(assistantText("s1", 2)).toBe("Hello"));
    expect(getSessionMock).not.toHaveBeenCalled();

    act(() => releaseTail());
    await waitFor(() => expect(getSessionMock).toHaveBeenCalled());
  });

  it("surfaces an errored resumed run even when the settle-refetch fails", async () => {
    seedLiveSession(2);
    resumeMock.mockReturnValue(
      scripted([streamError("resume boom", "SERVICE_UNAVAILABLE")]),
    );
    // Settle fetch fails → the in-stream error patch must survive (no stuck "…" placeholder).
    getSessionMock.mockRejectedValue(new Error("offline"));

    renderHook(() => useChatSessionController("s1"), { wrapper });

    await waitFor(() => {
      const node = getMessageByMessageId(
        useChatSessionStore.getState().sessions.get("s1")!.messageTree,
        2,
      );
      expect(node?.type).toBe("error");
    });
    const node = getMessageByMessageId(
      useChatSessionStore.getState().sessions.get("s1")!.messageTree,
      2,
    );
    expect(node?.message).toBe("resume boom");
    expect(node?.errorCode).toBe("SERVICE_UNAVAILABLE");
  });

  it("stops writing to a session the user has navigated away from", async () => {
    seedLiveSession(2);
    let releaseTail: () => void = () => {};
    const tail = new Promise<void>((resolve) => {
      releaseTail = resolve;
    });
    resumeMock.mockReturnValue(
      (async function* () {
        yield deltaPacket("A");
        yield cursor(1);
        await tail;
        yield deltaPacket("B");
        yield cursor(2);
      })(),
    );

    renderHook(() => useChatSessionController("s1"), { wrapper });

    await waitFor(() => expect(assistantText("s1", 2)).toBe("A"));

    act(() => useChatSessionStore.setState({ currentSessionId: "s2" }));
    act(() => releaseTail());

    // The post-switch packet must never land on s1, and no settle-refetch clobbers it.
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(assistantText("s1", 2)).toBe("A");
    expect(getSessionMock).not.toHaveBeenCalled();
  });

  it("reconnects before a blocked reader or readiness check finishes", async () => {
    seedLiveSession(2);
    const tail = Promise.withResolvers<void>();
    const status = Promise.withResolvers<{ is_processing: boolean }>();
    const statusMock = jest.mocked(getChatSessionStatus);
    statusMock.mockReturnValueOnce(status.promise);
    resumeMock
      .mockReturnValueOnce(
        (async function* () {
          yield deltaPacket("first");
          yield cursor(1);
          await tail.promise;
        })(),
      )
      .mockReturnValueOnce(scripted([deltaPacket("second"), cursor(1)]))
      .mockReturnValueOnce(scripted([]));
    getSessionMock.mockResolvedValue({
      chat_session_id: "s1",
      description: "",
      persona_id: 0,
      messages: backendMessages("saved"),
      packets: [[historyPacket("saved")]],
      time_created: "",
      current_stream: null,
    });

    const first = renderHook(() => useChatSessionController("s1"), { wrapper });
    await waitFor(() => expect(assistantText("s1", 2)).toBe("first"));
    const firstSignal = resumeMock.mock.calls[0]![3];
    first.unmount();
    expect(firstSignal.aborted).toBe(true);
    expect(useChatSessionStore.getState().sessions.get("s1")?.chatState).toBe(
      "settling",
    );
    expect(
      useChatSessionStore.getState().sessions.get("s1")?.abortController,
    ).toBeNull();

    const second = renderHook(() => useChatSessionController("s1"), {
      wrapper,
    });
    await waitFor(() => expect(statusMock).toHaveBeenCalledTimes(1));
    expect(resumeMock).toHaveBeenCalledTimes(2);
    second.unmount();
    const third = renderHook(() => useChatSessionController("s1"), { wrapper });
    await waitFor(() => expect(assistantText("s1", 2)).toBe("saved"));
    expect(resumeMock).toHaveBeenCalledTimes(3);
    expect(useChatSessionStore.getState().sessions.get("s1")?.chatState).toBe(
      "input",
    );

    await act(async () => {
      tail.resolve();
      status.resolve({ is_processing: false });
    });
    expect(getSessionMock).toHaveBeenCalledTimes(1);
    expect(assistantText("s1", 2)).toBe("saved");
    third.unmount();
  });

  it("continues readiness checks after reopening a response with a local error", async () => {
    seedLiveSession(2);
    const status = Promise.withResolvers<{ is_processing: boolean }>();
    jest.mocked(getChatSessionStatus).mockReturnValueOnce(status.promise);
    resumeMock.mockReturnValue(
      scripted([streamError("replay failed", "STREAM_GAP")]),
    );
    getSessionMock.mockResolvedValue({
      chat_session_id: "s1",
      description: "",
      persona_id: 0,
      messages: backendMessages("saved"),
      packets: [[historyPacket("saved")]],
      time_created: "",
      current_stream: null,
    });
    const first = renderHook(() => useChatSessionController("s1"), { wrapper });
    await waitFor(() => expect(getChatSessionStatus).toHaveBeenCalledTimes(1));
    first.unmount();
    const second = renderHook(() => useChatSessionController("s1"), {
      wrapper,
    });
    await waitFor(() =>
      expect(useChatSessionStore.getState().sessions.get("s1")?.chatState).toBe(
        "input",
      ),
    );
    expect(resumeMock).toHaveBeenCalledTimes(1);
    const tree = useChatSessionStore.getState().sessions.get("s1")!.messageTree;
    expect(getMessageByMessageId(tree, 2)?.message).toBe("saved");
    await act(async () => {
      status.resolve({ is_processing: false });
    });
    expect(getSessionMock).toHaveBeenCalledTimes(1);
    second.unmount();
  });

  it("loads the current answer when an earlier response failed", async () => {
    seedLiveSession(2);
    const previous = backendMessages("old failure").map((message) => ({
      ...message,
      message_id: message.message_id + 10,
      parent_message:
        message.parent_message == null ? null : message.parent_message + 10,
      latest_child_message:
        message.latest_child_message == null
          ? null
          : message.latest_child_message + 10,
      error: message.message_type === "assistant" ? "old failure" : null,
    }));
    useChatSessionStore
      .getState()
      .hydrateSession(
        "s1",
        processRawChatHistory([...previous, ...backendMessages("")], [[], []]),
      );
    getSessionMock.mockResolvedValue({
      chat_session_id: "s1",
      description: "",
      persona_id: 0,
      messages: [...previous, ...backendMessages("saved answer")],
      packets: [[], [historyPacket("saved answer")]],
      time_created: "",
      current_stream: null,
    });
    resumeMock.mockReturnValue(
      (async function* (): AsyncGenerator<StreamEvent> {
        throw new StreamHttpError("no replay", 404);
      })(),
    );

    renderHook(() => useChatSessionController("s1"), { wrapper });
    await waitFor(() => expect(assistantText("s1", 2)).toBe("saved answer"));
    const tree = useChatSessionStore.getState().sessions.get("s1")!.messageTree;
    expect(getMessageByMessageId(tree, 12)?.message).toBe("old failure");
  });

  it.each([
    {
      status: undefined,
      errorCode: "STREAM_GAP",
      savedAnswer: "saved answer",
      retainsError: false,
    },
    {
      status: undefined,
      errorCode: undefined,
      savedAnswer: "saved answer",
      retainsError: false,
    },
    {
      status: undefined,
      errorCode: "STREAM_GAP",
      savedAnswer: "",
      retainsError: true,
    },
    {
      status: undefined,
      errorCode: "RESPONSE_SAVE_ERROR",
      savedAnswer: "",
      retainsError: true,
    },
    {
      status: undefined,
      errorCode: "RESPONSE_SAVE_ERROR",
      savedAnswer: "saved answer",
      retainsError: false,
    },
    ...(
      [null, "running", "suspended", "complete", "limit", "cancelled"] as const
    ).map((status) => ({
      errorCode: "RESPONSE_SAVE_ERROR",
      savedAnswer:
        "Response was terminated prior to completion, try regenerating.",
      status,
      retainsError: status === null || status === "running",
    })),
  ])(
    "settles error $errorCode with saved status $status and answer '$savedAnswer'",
    async ({ errorCode, savedAnswer, retainsError, status }) => {
      seedLiveSession(2);
      resumeMock.mockReturnValue(
        scripted([streamError("replay failed", errorCode)]),
      );
      getSessionMock.mockResolvedValue({
        chat_session_id: "s1",
        description: "",
        persona_id: 0,
        messages: backendMessages(savedAnswer).map((message) =>
          message.message_type === "user"
            ? { ...message, message: "saved question" }
            : { ...message, response_status: status },
        ),
        packets: [[historyPacket(savedAnswer || "partial output")]],
        time_created: "",
        current_stream: null,
      });

      renderHook(() => useChatSessionController("s1"), { wrapper });
      await waitFor(() =>
        expect(
          useChatSessionStore.getState().sessions.get("s1")?.chatState,
        ).toBe("input"),
      );
      const tree = useChatSessionStore
        .getState()
        .sessions.get("s1")!.messageTree;
      expect(getMessageByMessageId(tree, 1)?.message).toBe("saved question");
      expect(getMessageByMessageId(tree, 2)).toMatchObject(
        retainsError
          ? {
              type: "error",
              message: "replay failed",
              errorCode: errorCode ?? null,
            }
          : { type: "assistant", message: savedAnswer },
      );
    },
  );

  // A send that dropped before the request arrived failed locally; the server parked the answer.
  it("shows the waiting card of a parked answer over a failed local copy", async () => {
    seedLiveSession(2);
    resumeMock.mockReturnValue(
      scripted([streamError("connection lost", "STREAM_GAP")]),
    );
    const waiting: Packet = {
      placement: { turn_index: 0 },
      obj: {
        type: PacketType.TOOL_APPROVAL_REQUEST,
        approval_id: "parked-1",
        tool_call_id: "c1",
        tool_name: "lookup",
        display_name: "Lookup",
        arguments: {},
      },
    };
    getSessionMock.mockResolvedValue({
      chat_session_id: "s1",
      description: "",
      persona_id: 0,
      messages: backendMessages("").map((message) =>
        message.message_type === "assistant"
          ? { ...message, response_status: "suspended" }
          : message,
      ),
      packets: [
        [
          waiting,
          {
            placement: { turn_index: 0 },
            obj: {
              type: PacketType.STOP,
              stop_reason: StopReason.AWAITING_USER,
            },
          },
        ],
      ],
      time_created: "",
      current_stream: null,
    });

    renderHook(() => useChatSessionController("s1"), { wrapper });
    await waitFor(() =>
      expect(useChatSessionStore.getState().sessions.get("s1")?.chatState).toBe(
        "input",
      ),
    );
    expect(
      getMessageByMessageId(
        useChatSessionStore.getState().sessions.get("s1")!.messageTree,
        2,
      )?.type,
    ).toBe("assistant");
    expect(waitingIds()).toEqual(["parked-1"]);
  });

  it("replaces a replay error with the saved response failure", async () => {
    seedLiveSession(2);
    resumeMock.mockReturnValue(
      scripted([streamError("replay failed", "STREAM_GAP")]),
    );
    getSessionMock.mockResolvedValue({
      chat_session_id: "s1",
      description: "",
      persona_id: 0,
      messages: backendMessages("").map((message) =>
        message.message_type === "assistant"
          ? { ...message, error: "provider failed", response_status: "error" }
          : message,
      ),
      packets: [],
      time_created: "",
      current_stream: null,
    });

    renderHook(() => useChatSessionController("s1"), { wrapper });
    await waitFor(() => {
      const tree = useChatSessionStore
        .getState()
        .sessions.get("s1")!.messageTree;
      expect(getMessageByMessageId(tree, 2)).toMatchObject({
        type: "error",
        message: "provider failed",
      });
    });
  });

  it("does not resume when the snapshot reports no live run", async () => {
    seedLiveSession(null);

    renderHook(() => useChatSessionController("s1"), { wrapper });

    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(resumeMock).not.toHaveBeenCalled();
  });

  it("does not resume while a local send owns the session", async () => {
    seedLiveSession(2);
    useChatSessionStore
      .getState()
      .setAbortController("s1", new AbortController());

    renderHook(() => useChatSessionController("s1"), { wrapper });

    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(resumeMock).not.toHaveBeenCalled();
  });

  it("does not resume when the saved session has no assistant node for the run id", async () => {
    seedLiveSession(999);
    getSessionMock.mockResolvedValue({
      chat_session_id: "s1",
      description: "",
      persona_id: 0,
      messages: backendMessages("saved"),
      packets: [[historyPacket("saved")]],
      time_created: "",
      current_stream: null,
    });

    renderHook(() => useChatSessionController("s1"), { wrapper });

    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(resumeMock).not.toHaveBeenCalled();
  });

  it("does not clobber a send that took over during the settle-refetch", async () => {
    seedLiveSession(2);
    resumeMock.mockReturnValue(scripted([deltaPacket("resumed"), cursor(1)]));
    // Hold the settle-refetch open so a send can race in while resume awaits it.
    let resolveSettle: (v: BackendChatSession) => void = () => {};
    getSessionMock.mockReturnValue(
      new Promise<BackendChatSession>((resolve) => {
        resolveSettle = resolve;
      }),
    );

    renderHook(() => useChatSessionController("s1"), { wrapper });

    await waitFor(() => expect(assistantText("s1", 2)).toBe("resumed"));
    await waitFor(() => expect(getSessionMock).toHaveBeenCalled());

    // A send takes over and completes: setAbortController replaces resume's token, then a completed
    // run leaves it null (still not resume's token).
    act(() => {
      useChatSessionStore
        .getState()
        .setAbortController("s1", new AbortController());
      useChatSessionStore.getState().setAbortController("s1", null);
    });

    // Settle resolves with a snapshot that predates the send.
    act(() =>
      resolveSettle({
        chat_session_id: "s1",
        description: "Named",
        persona_id: 0,
        messages: backendMessages("stale"),
        packets: [[historyPacket("stale")]],
        time_created: "",
        current_stream: null,
      }),
    );

    // hydrateSession must be skipped (resume no longer owns the stream), so the streamed content
    // stands instead of the stale snapshot.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(assistantText("s1", 2)).toBe("resumed");
  });

  it("stays silent when the run is already gone (404), then settles", async () => {
    seedLiveSession(2);
    const warn = jest.spyOn(console, "warn").mockImplementation(() => {});
    getSessionMock.mockResolvedValue({
      chat_session_id: "s1",
      description: "Named",
      persona_id: 0,
      messages: backendMessages("done"),
      packets: [[historyPacket("done")]],
      time_created: "",
      current_stream: null,
    });
    resumeMock.mockReturnValue(
      (async function* (): AsyncGenerator<StreamEvent> {
        throw new StreamHttpError("no resumable run", 404);
      })(),
    );

    renderHook(() => useChatSessionController("s1"), { wrapper });

    await waitFor(() => expect(getSessionMock).toHaveBeenCalled());
    expect(warn).not.toHaveBeenCalled();
    warn.mockRestore();
  });

  it("logs an unexpected resume failure before settling", async () => {
    seedLiveSession(2);
    const warn = jest.spyOn(console, "warn").mockImplementation(() => {});
    getSessionMock.mockResolvedValue({
      chat_session_id: "s1",
      description: "Named",
      persona_id: 0,
      messages: backendMessages("done"),
      packets: [[historyPacket("done")]],
      time_created: "",
      current_stream: null,
    });
    resumeMock.mockReturnValue(
      (async function* (): AsyncGenerator<StreamEvent> {
        throw new Error("network down");
      })(),
    );

    renderHook(() => useChatSessionController("s1"), { wrapper });

    await waitFor(() => expect(warn).toHaveBeenCalled());
    warn.mockRestore();
  });

  it("keeps shown packets when a replay fails partway, then reattaches from its cursor", async () => {
    seedLiveSession(2);
    const approval = {
      placement: { turn_index: 0 },
      obj: {
        type: PacketType.TOOL_APPROVAL_REQUEST,
        approval_id: "a1",
        tool_call_id: "c1",
        tool_name: "lookup",
        display_name: "Lookup",
        arguments: {},
      },
    } as unknown as Packet;
    useChatSessionStore
      .getState()
      .patchNode("s1", 2, { packets: [historyPacket("A"), approval] });
    jest.mocked(getChatSessionStatus).mockResolvedValue({
      is_processing: true,
      current_stream: { stream_id: 2, response_ids: [2] },
    });
    const resumed = Promise.withResolvers<void>();
    resumeMock
      .mockReturnValueOnce(
        (async function* (): AsyncGenerator<StreamEvent> {
          yield startPacket("A");
          yield cursor(1, false);
          yield approval;
          throw new TypeError("Network request failed");
        })(),
      )
      .mockReturnValueOnce(
        (async function* (): AsyncGenerator<StreamEvent> {
          await resumed.promise;
          yield approval;
          yield cursor(2);
          await new Promise(() => {});
        })(),
      );

    const { unmount } = renderHook(() => useChatSessionController("s1"), {
      wrapper,
    });

    await waitFor(
      () =>
        expect(resumeMock).toHaveBeenLastCalledWith(
          "s1",
          2,
          1,
          expect.anything(),
        ),
      { timeout: 3000 },
    );
    expect(waitingIds()).toEqual(["a1"]);
    await act(async () => resumed.resolve());
    await waitFor(() =>
      expect(useChatSessionStore.getState().sessions.get("s1")?.chatState).toBe(
        "streaming",
      ),
    );
    const node = getMessageByMessageId(
      useChatSessionStore.getState().sessions.get("s1")!.messageTree,
      2,
    );
    await waitFor(() =>
      expect(
        getMessageByMessageId(
          useChatSessionStore.getState().sessions.get("s1")!.messageTree,
          2,
        )?.packets,
      ).not.toBe(node?.packets),
    );
    expect(assistantText("s1", 2)).toBe("A");
    expect(waitingIds()).toEqual(["a1"]);
    expect(
      getMessageByMessageId(
        useChatSessionStore.getState().sessions.get("s1")!.messageTree,
        2,
      )?.packets,
    ).toHaveLength(2);
    unmount();
  });

  it("follows a paused response's continuation stream into the response it names", async () => {
    seedLiveSession(2);
    // The continuation's stream ID is no message ID; `response_ids` names the response.
    jest.mocked(getChatSessionStatus).mockResolvedValueOnce({
      is_processing: true,
      current_stream: { stream_id: 7, response_ids: [2] },
    });
    getSessionMock.mockResolvedValueOnce({
      chat_session_id: "s1",
      description: "",
      persona_id: 0,
      messages: backendMessages("asked done"),
      packets: [[historyPacket("asked done")]],
      time_created: "",
      current_stream: null,
    });
    resumeMock
      .mockReturnValueOnce(
        scripted([
          startPacket("asked"),
          {
            placement: { turn_index: 0 },
            obj: {
              type: PacketType.STOP,
              stop_reason: StopReason.AWAITING_USER,
            },
          },
          cursor(2),
        ]),
      )
      .mockReturnValueOnce(
        scripted([
          startPacket("asked"),
          deltaPacket(" done"),
          stopPacket(),
          { stream_id: 7, next_cursor: 3, replay_complete: true },
        ]),
      );

    renderHook(() => useChatSessionController("s1"), { wrapper });

    await waitFor(
      () =>
        expect(
          useChatSessionStore.getState().sessions.get("s1")?.chatState,
        ).toBe("input"),
      { timeout: 3000 },
    );
    expect(resumeMock.mock.calls.map((call) => [call[1], call[2]])).toEqual([
      [2, 0],
      [7, 0],
    ]);
    // Only the settle loads the saved session.
    expect(getSessionMock).toHaveBeenCalledTimes(1);
    expect(assistantText("s1", 2)).toBe("asked done");
  });

  // A paused response's turn can keep running for a sibling; its resume is a later stream.
  it("keeps reading status after a pause until a new stream names the response", async () => {
    seedLiveSession(2);
    jest
      .mocked(getChatSessionStatus)
      .mockResolvedValueOnce({
        is_processing: true,
        current_stream: { stream_id: 2, response_ids: [2, 3] },
      })
      .mockResolvedValueOnce({
        is_processing: true,
        current_stream: { stream_id: 2, response_ids: [2, 3] },
      })
      .mockResolvedValueOnce({
        is_processing: true,
        current_stream: { stream_id: 9, response_ids: [2] },
      });
    getSessionMock.mockResolvedValueOnce({
      chat_session_id: "s1",
      description: "",
      persona_id: 0,
      messages: backendMessages("asked done"),
      packets: [[historyPacket("asked done")]],
      time_created: "",
      current_stream: null,
    });
    resumeMock
      .mockReturnValueOnce(
        scripted([
          startPacket("asked"),
          {
            placement: { turn_index: 0 },
            obj: {
              type: PacketType.STOP,
              stop_reason: StopReason.AWAITING_USER,
            },
          },
          cursor(2),
        ]),
      )
      .mockReturnValueOnce(
        scripted([
          startPacket("asked"),
          deltaPacket(" done"),
          stopPacket(),
          { stream_id: 9, next_cursor: 3, replay_complete: true },
        ]),
      );

    renderHook(() => useChatSessionController("s1"), { wrapper });

    await waitFor(() =>
      expect(useChatSessionStore.getState().sessions.get("s1")?.chatState).toBe(
        "input",
      ),
    );
    // The paused stream is never read again.
    expect(resumeMock.mock.calls.map((call) => [call[1], call[2]])).toEqual([
      [2, 0],
      [9, 0],
    ]);
    expect(getChatSessionStatus).toHaveBeenCalledTimes(4);
  });

  // A continuation's replay holds every saved resolution, and its live part sends the resolution
  // of a call the run continues again.
  it("shows one decided card when a continuation repeats a resolution", async () => {
    seedLiveSession(2);
    const request: StreamEvent = {
      placement: { turn_index: 0 },
      obj: {
        type: PacketType.TOOL_APPROVAL_REQUEST,
        approval_id: "a1",
        tool_call_id: "c1",
        tool_name: "lookup",
        display_name: "Lookup",
        arguments: {},
      },
    };
    const resolved: StreamEvent = {
      placement: { turn_index: 0 },
      obj: {
        type: PacketType.TOOL_APPROVAL_RESOLVED,
        approval_id: "a1",
        outcome: "approved",
      },
    };
    let release: () => void = () => {};
    resumeMock.mockReturnValueOnce(
      (async function* (): AsyncGenerator<StreamEvent> {
        yield request;
        yield resolved;
        yield {
          placement: { turn_index: 0 },
          obj: { type: PacketType.REPLAY_END },
        };
        yield cursor(3);
        yield resolved;
        yield startPacket("Sunny");
        yield cursor(5);
        await new Promise<void>((resolve) => {
          release = resolve;
        });
      })(),
    );

    const { unmount } = renderHook(() => useChatSessionController("s1"), {
      wrapper,
    });

    await waitFor(() => expect(assistantText("s1", 2)).toBe("Sunny"));
    const tree = useChatSessionStore.getState().sessions.get("s1")!.messageTree;
    const packets = getMessageByMessageId(tree, 2)?.packets ?? [];
    expect(
      readToolApprovals(packets).map((entry) => [
        entry.request.approval_id,
        toolApprovalStatus(entry, undefined),
      ]),
    ).toEqual([["a1", "approved"]]);
    // The replay boundary is not output.
    expect(packets.map((packet) => packet.obj.type)).not.toContain(
      PacketType.REPLAY_END,
    );
    unmount();
    release();
  });

  it("follows a new stream instead of retrying one without a buffer", async () => {
    seedLiveSession(2);
    jest
      .mocked(getChatSessionStatus)
      .mockResolvedValueOnce({
        is_processing: true,
        current_stream: { stream_id: 2, response_ids: [2] },
      })
      .mockResolvedValueOnce({
        is_processing: true,
        current_stream: { stream_id: 4, response_ids: [4] },
      });
    const nextTurn: BackendMessage[] = [
      ...backendMessages("first"),
      {
        message_id: 3,
        message_type: "user",
        parent_message: 2,
        latest_child_message: 4,
        message: "queued",
        files: [],
        time_sent: "",
        error: null,
      },
      {
        message_id: 4,
        message_type: "assistant",
        parent_message: 3,
        latest_child_message: null,
        message: "",
        files: [],
        time_sent: "",
        error: null,
      },
    ];
    nextTurn[1] = { ...nextTurn[1]!, latest_child_message: 3 };
    getSessionMock
      .mockResolvedValueOnce({
        chat_session_id: "s1",
        description: "",
        persona_id: 0,
        messages: nextTurn,
        packets: [[historyPacket("first")], []],
        time_created: "",
        // Only the status check leads to the new stream.
        current_stream: null,
      })
      .mockResolvedValueOnce({
        chat_session_id: "s1",
        description: "",
        persona_id: 0,
        messages: nextTurn.map((message) =>
          message.message_id === 4 ? { ...message, message: "next" } : message,
        ),
        packets: [[historyPacket("first")], [historyPacket("next")]],
        time_created: "",
        current_stream: null,
      });
    resumeMock
      .mockReturnValueOnce(
        (async function* (): AsyncGenerator<StreamEvent> {
          throw new StreamHttpError("no resumable run", 404);
        })(),
      )
      .mockReturnValueOnce(
        scripted([
          startPacket("next"),
          stopPacket(),
          { stream_id: 4, next_cursor: 2, replay_complete: true },
        ]),
      );

    renderHook(() => useChatSessionController("s1"), { wrapper });

    await waitFor(
      () =>
        expect(
          useChatSessionStore.getState().sessions.get("s1")?.chatState,
        ).toBe("input"),
      { timeout: 3000 },
    );
    expect(resumeMock.mock.calls.map((call) => [call[1], call[2]])).toEqual([
      [2, 0],
      [4, 0],
    ]);
    expect(assistantText("s1", 4)).toBe("next");
  });

  it("retries loading an unseen response while its stream runs", async () => {
    seedLiveSession(null);
    useChatSessionStore.getState().updateChatState("s1", "settling");
    jest.mocked(getChatSessionStatus).mockResolvedValue({
      is_processing: true,
      current_stream: { stream_id: 4, response_ids: [4] },
    });
    const warn = jest.spyOn(console, "warn").mockImplementation(() => {});
    const nextTurn: BackendMessage[] = [
      ...backendMessages("first"),
      {
        message_id: 3,
        message_type: "user",
        parent_message: 2,
        latest_child_message: 4,
        message: "asked elsewhere",
        files: [],
        time_sent: "",
        error: null,
      },
      {
        message_id: 4,
        message_type: "assistant",
        parent_message: 3,
        latest_child_message: null,
        message: "",
        files: [],
        time_sent: "",
        error: null,
      },
    ];
    nextTurn[1] = { ...nextTurn[1]!, latest_child_message: 3 };
    getSessionMock
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce({
        chat_session_id: "s1",
        description: "",
        persona_id: 0,
        messages: nextTurn,
        packets: [[historyPacket("first")], []],
        time_created: "",
        current_stream: null,
      });
    resumeMock.mockReturnValueOnce(
      (async function* (): AsyncGenerator<StreamEvent> {
        yield startPacket("live");
        yield { stream_id: 4, next_cursor: 1, replay_complete: true };
        await new Promise(() => {});
      })(),
    );

    const { unmount } = renderHook(() => useChatSessionController("s1"), {
      wrapper,
    });

    await waitFor(() => expect(assistantText("s1", 4)).toBe("live"), {
      timeout: 3000,
    });
    expect(getSessionMock).toHaveBeenCalledTimes(2);
    expect(resumeMock).toHaveBeenCalledWith("s1", 4, 0, expect.anything());
    unmount();
    warn.mockRestore();
  });

  it.each([
    ["a clean end before the first cursor", () => scripted([])],
    [
      "a 503",
      () =>
        (async function* (): AsyncGenerator<StreamEvent> {
          throw new StreamHttpError("unavailable", 503);
        })(),
    ],
    [
      "a 429",
      () =>
        (async function* (): AsyncGenerator<StreamEvent> {
          throw new StreamHttpError("slow down", 429);
        })(),
    ],
  ])("reattaches to the same stream after %s", async (_case, firstAttempt) => {
    seedLiveSession(2);
    jest.mocked(getChatSessionStatus).mockResolvedValue({
      is_processing: true,
      current_stream: { stream_id: 2, response_ids: [2] },
    });
    const warn = jest.spyOn(console, "warn").mockImplementation(() => {});
    resumeMock.mockReturnValueOnce(firstAttempt()).mockReturnValueOnce(
      (async function* (): AsyncGenerator<StreamEvent> {
        yield startPacket("back");
        yield cursor(1);
        await new Promise(() => {});
      })(),
    );

    const { unmount } = renderHook(() => useChatSessionController("s1"), {
      wrapper,
    });

    await waitFor(() => expect(assistantText("s1", 2)).toBe("back"), {
      timeout: 3000,
    });
    expect(resumeMock.mock.calls.map((call) => [call[1], call[2]])).toEqual([
      [2, 0],
      [2, 0],
    ]);
    unmount();
    warn.mockRestore();
  });

  it("reports an auth failure through the status poll after a 401 resume", async () => {
    seedLiveSession(2);
    const warn = jest.spyOn(console, "warn").mockImplementation(() => {});
    resumeMock.mockReturnValueOnce(
      (async function* (): AsyncGenerator<StreamEvent> {
        throw new StreamHttpError("expired", 401);
      })(),
    );
    jest
      .mocked(getChatSessionStatus)
      .mockRejectedValue(new ApiError({ status: 401, detail: "Signed out" }));

    renderHook(() => useChatSessionController("s1"), { wrapper });

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Signed out"));
    expect(useChatSessionStore.getState().sessions.get("s1")?.chatState).toBe(
      "unconfirmed",
    );
    expect(resumeMock).toHaveBeenCalledTimes(1);
    warn.mockRestore();
  });

  it("releases a send-started recovery when the user leaves, so reopening attaches", async () => {
    seedLiveSession(2);
    jest.mocked(getChatSessionStatus).mockResolvedValue({
      is_processing: true,
      current_stream: { stream_id: 2, response_ids: [2] },
    });
    resumeMock
      .mockImplementationOnce((_id, _streamId, _cursor, signal) =>
        (async function* (): AsyncGenerator<StreamEvent> {
          // A stalled connection: nothing arrives until the reader is aborted.
          await new Promise<void>((resolve) =>
            signal.addEventListener("abort", () => resolve(), { once: true }),
          );
        })(),
      )
      .mockImplementationOnce(() =>
        (async function* (): AsyncGenerator<StreamEvent> {
          yield startPacket("again");
          yield cursor(1);
          await new Promise(() => {});
        })(),
      );
    const handOff = new AbortController();
    void recoverChatSession(
      "s1",
      { stream_id: 2, response_ids: [2] },
      SERVER_URL,
      client,
      handOff,
    );
    await waitFor(() => expect(resumeMock).toHaveBeenCalledTimes(1));

    const first = renderHook(() => useChatSessionController("s1"), {
      wrapper,
    });
    first.unmount();
    expect(handOff.signal.aborted).toBe(true);
    const second = renderHook(() => useChatSessionController("s1"), {
      wrapper,
    });

    await waitFor(() => expect(assistantText("s1", 2)).toBe("again"));
    expect(resumeMock).toHaveBeenCalledTimes(2);
    second.unmount();
  });

  it("does not render heartbeat packets during resume", async () => {
    seedLiveSession(2);
    let releaseTail: () => void = () => {};
    const tail = new Promise<void>((resolve) => {
      releaseTail = resolve;
    });
    const heartbeat = {
      placement: { turn_index: 0 },
      obj: { type: "chat_heartbeat" },
    } as unknown as StreamEvent;
    getSessionMock.mockResolvedValue({
      chat_session_id: "s1",
      description: "Named",
      persona_id: 0,
      messages: backendMessages("AB"),
      packets: [[historyPacket("AB")]],
      time_created: "",
      current_stream: null,
    });
    resumeMock.mockReturnValue(
      (async function* () {
        yield deltaPacket("A");
        yield heartbeat;
        yield deltaPacket("B");
        yield cursor(2);
        await tail;
      })(),
    );

    renderHook(() => useChatSessionController("s1"), { wrapper });

    await waitFor(() => expect(assistantText("s1", 2)).toBe("AB"));
    const tree = useChatSessionStore.getState().sessions.get("s1")?.messageTree;
    const node = tree ? getMessageByMessageId(tree, 2) : undefined;
    // Heartbeat excluded — only the two content deltas landed.
    expect(node?.packets).toHaveLength(2);

    act(() => releaseTail());
  });
});

describe("watchBackgroundAgents", () => {
  const agentRequest: Packet = {
    placement: { turn_index: 0 },
    obj: {
      type: PacketType.TOOL_APPROVAL_REQUEST,
      approval_id: "agent-2",
      tool_call_id: "c2",
      tool_name: "lookup",
      display_name: "Lookup",
      arguments: {},
      agent_name: "Researcher",
    },
  };
  function saved(packets: Packet[], version: string): BackendChatSession {
    return {
      chat_session_id: "s1",
      description: "",
      persona_id: 0,
      messages: backendMessages("asked"),
      packets: [packets],
      time_created: "",
      current_stream: null,
      approvals_version: version,
    };
  }

  beforeEach(() => {
    jest.clearAllMocks();
    jest.useFakeTimers();
    client = new QueryClient();
    useChatSessionStore.setState({
      currentSessionId: null,
      sessions: new Map(),
    });
    useToolApprovalUi.setState({ localStatuses: new Map(), nudgeSeq: 0 });
  });
  afterEach(() => {
    jest.useRealTimers();
  });

  // A decided agent that waits to resume counts as active, so reads go on until it stops.
  it("loads an agent's later request while the decided agent runs, then stops once it stops", async () => {
    getSessionMock.mockResolvedValueOnce(saved([historyPacket("asked")], "v1"));
    const baseline = await getChatSession("s1");
    useChatSessionStore
      .getState()
      .hydrateSession(
        "s1",
        processRawChatHistory(baseline.messages, baseline.packets),
        baseline.approvals_version,
      );
    useChatSessionStore.setState({ currentSessionId: "s1" });
    jest
      .mocked(getChatSessionStatus)
      .mockResolvedValueOnce({
        is_processing: false,
        has_active_subagents: true,
        approvals_version: "v1",
      })
      .mockResolvedValueOnce({
        is_processing: false,
        has_active_subagents: true,
        approvals_version: "v2",
      })
      .mockResolvedValueOnce({
        is_processing: false,
        has_active_subagents: false,
        approvals_version: "v2",
      });
    getSessionMock.mockResolvedValue(
      saved([historyPacket("asked"), agentRequest], "v2"),
    );

    const watch = watchBackgroundAgents("s1", SERVER_URL, client);
    await jest.advanceTimersByTimeAsync(3000);
    await watch;

    expect(waitingIds()).toEqual(["agent-2"]);
    expect(getChatSessionStatus).toHaveBeenCalledTimes(3);
    // The baseline load, the reload for the changed version and the last reload.
    expect(getSessionMock).toHaveBeenCalledTimes(3);
    await jest.advanceTimersByTimeAsync(3000);
    expect(getChatSessionStatus).toHaveBeenCalledTimes(3);
  });

  it("stops after one read when no background agent runs or waits to resume", async () => {
    getSessionMock.mockResolvedValue(saved([historyPacket("done")], "v1"));
    const baseline = await getChatSession("s1");
    useChatSessionStore
      .getState()
      .hydrateSession(
        "s1",
        processRawChatHistory(baseline.messages, baseline.packets),
        baseline.approvals_version,
      );
    useChatSessionStore.setState({ currentSessionId: "s1" });
    jest.mocked(getChatSessionStatus).mockResolvedValue({
      is_processing: false,
      has_active_subagents: false,
      approvals_version: "v1",
    });

    const watch = watchBackgroundAgents("s1", SERVER_URL, client);
    await jest.advanceTimersByTimeAsync(6000);
    await watch;

    expect(getChatSessionStatus).toHaveBeenCalledTimes(1);
    expect(getSessionMock).toHaveBeenCalledTimes(2);
  });

  it("keeps one watch per chat for quick agent decisions, with one last reload", async () => {
    getSessionMock.mockResolvedValue(saved([historyPacket("done")], "v1"));
    const baseline = await getChatSession("s1");
    useChatSessionStore
      .getState()
      .hydrateSession(
        "s1",
        processRawChatHistory(baseline.messages, baseline.packets),
        baseline.approvals_version,
      );
    useChatSessionStore.setState({ currentSessionId: "s1" });
    const status = jest.mocked(getChatSessionStatus);
    status
      .mockResolvedValueOnce({
        is_processing: false,
        has_active_subagents: true,
        approvals_version: "v1",
      })
      .mockResolvedValue({
        is_processing: false,
        has_active_subagents: false,
        approvals_version: "v1",
      });

    const first = watchBackgroundAgents("s1", SERVER_URL, client);
    const second = watchBackgroundAgents("s1", SERVER_URL, client);
    await jest.advanceTimersByTimeAsync(6000);
    await Promise.all([first, second]);

    expect(status).toHaveBeenCalledTimes(2);
    expect(getSessionMock).toHaveBeenCalledTimes(2);
  });

  // The second decision lands while the watch's read is in flight, so that read may predate it.
  it("reads again for a decision made during an in-flight read", async () => {
    getSessionMock.mockResolvedValue(saved([historyPacket("done")], "v1"));
    const baseline = await getChatSession("s1");
    useChatSessionStore
      .getState()
      .hydrateSession(
        "s1",
        processRawChatHistory(baseline.messages, baseline.packets),
        baseline.approvals_version,
      );
    useChatSessionStore.setState({ currentSessionId: "s1" });
    const status = jest.mocked(getChatSessionStatus);
    const quiet = {
      is_processing: false,
      has_active_subagents: false,
      approvals_version: "v1",
    };
    let answer: (value: typeof quiet) => void = () => {};
    status
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            answer = resolve;
          }),
      )
      .mockResolvedValue(quiet);

    const first = watchBackgroundAgents("s1", SERVER_URL, client);
    await jest.advanceTimersByTimeAsync(1000);
    expect(status).toHaveBeenCalledTimes(1);
    const second = watchBackgroundAgents("s1", SERVER_URL, client);
    answer(quiet);
    await jest.advanceTimersByTimeAsync(6000);
    await Promise.all([first, second]);

    expect(status).toHaveBeenCalledTimes(2);
  });

  async function openIdle(version: string) {
    getSessionMock.mockResolvedValueOnce(
      saved([historyPacket("asked")], version),
    );
    const baseline = await getChatSession("s1");
    useChatSessionStore
      .getState()
      .hydrateSession(
        "s1",
        processRawChatHistory(baseline.messages, baseline.packets),
        baseline.approvals_version,
      );
    useChatSessionStore.setState({ currentSessionId: "s1" });
  }

  // A parked agent does not count as active, so the read that reports its request is the last.
  it("retries a failed reload before the watch ends", async () => {
    await openIdle("v1");
    jest.mocked(getChatSessionStatus).mockResolvedValue({
      is_processing: false,
      has_active_subagents: false,
      approvals_version: "v2",
    });
    getSessionMock
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue(saved([historyPacket("asked"), agentRequest], "v2"));

    const watch = watchBackgroundAgents("s1", SERVER_URL, client);
    await jest.advanceTimersByTimeAsync(6000);
    await watch;

    expect(waitingIds()).toEqual(["agent-2"]);
    expect(getChatSessionStatus).toHaveBeenCalledTimes(2);
  });

  it("retries a failed reload for a version while the agents run", async () => {
    await openIdle("v1");
    jest
      .mocked(getChatSessionStatus)
      .mockResolvedValueOnce({
        is_processing: false,
        has_active_subagents: true,
        approvals_version: "v2",
      })
      .mockResolvedValue({
        is_processing: false,
        has_active_subagents: true,
        approvals_version: "v2",
      });
    getSessionMock
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue(saved([historyPacket("asked"), agentRequest], "v2"));

    void watchBackgroundAgents("s1", SERVER_URL, client);
    await jest.advanceTimersByTimeAsync(2000);

    expect(waitingIds()).toEqual(["agent-2"]);
    useChatSessionStore.setState({ currentSessionId: null });
    await jest.advanceTimersByTimeAsync(1000);
  });

  it("watches the agents of a chat that opens idle while they run", async () => {
    await openIdle("v1");
    client.setQueryData(
      QUERY_KEYS.chatSession(SERVER_URL, "s1"),
      saved([historyPacket("asked")], "v1"),
    );
    jest
      .mocked(getChatSessionStatus)
      .mockResolvedValueOnce({
        is_processing: false,
        has_active_subagents: true,
        approvals_version: "v1",
      })
      .mockResolvedValue({
        is_processing: false,
        has_active_subagents: false,
        approvals_version: "v2",
      });
    getSessionMock.mockResolvedValue(
      saved([historyPacket("asked"), agentRequest], "v2"),
    );

    const view = renderHook(() => useChatSessionController("s1"), { wrapper });
    await jest.advanceTimersByTimeAsync(3000);

    expect(waitingIds()).toEqual(["agent-2"]);
    view.unmount();
  });

  it("retries a failed status read of a chat that opens idle", async () => {
    await openIdle("v1");
    client.setQueryData(
      QUERY_KEYS.chatSession(SERVER_URL, "s1"),
      saved([historyPacket("asked")], "v1"),
    );
    jest
      .mocked(getChatSessionStatus)
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce({
        is_processing: false,
        has_active_subagents: true,
        approvals_version: "v2",
      })
      .mockResolvedValue({
        is_processing: false,
        has_active_subagents: false,
        approvals_version: "v2",
      });
    getSessionMock.mockResolvedValue(
      saved([historyPacket("asked"), agentRequest], "v2"),
    );

    const view = renderHook(() => useChatSessionController("s1"), { wrapper });
    await jest.advanceTimersByTimeAsync(3000);

    expect(waitingIds()).toEqual(["agent-2"]);
    view.unmount();
  });

  it("reads status once and loads nothing for a chat that opens with no agent work", async () => {
    await openIdle("v1");
    client.setQueryData(
      QUERY_KEYS.chatSession(SERVER_URL, "s1"),
      saved([historyPacket("asked")], "v1"),
    );
    jest.mocked(getChatSessionStatus).mockResolvedValue({
      is_processing: false,
      has_active_subagents: false,
      approvals_version: "v1",
    });

    const view = renderHook(() => useChatSessionController("s1"), { wrapper });
    await jest.advanceTimersByTimeAsync(3000);

    expect(getChatSessionStatus).toHaveBeenCalledTimes(1);
    // Only the baseline load.
    expect(getSessionMock).toHaveBeenCalledTimes(1);
    view.unmount();
  });

  it("watches an agent that parked after the chat opened idle", async () => {
    await openIdle("v1");
    client.setQueryData(
      QUERY_KEYS.chatSession(SERVER_URL, "s1"),
      saved([historyPacket("asked")], "v1"),
    );
    jest.mocked(getChatSessionStatus).mockResolvedValue({
      is_processing: false,
      has_active_subagents: false,
      approvals_version: "v2",
    });
    getSessionMock.mockResolvedValue(
      saved([historyPacket("asked"), agentRequest], "v2"),
    );

    const view = renderHook(() => useChatSessionController("s1"), { wrapper });
    await jest.advanceTimersByTimeAsync(3000);

    expect(waitingIds()).toEqual(["agent-2"]);
    view.unmount();
  });

  // An agent's result wakes the root, which processes before it publishes its stream.
  it("follows a root continuation whose stream starts after a processing read", async () => {
    await openIdle("v1");
    jest
      .mocked(getChatSessionStatus)
      .mockResolvedValueOnce({
        is_processing: true,
        has_active_subagents: false,
        current_stream: null,
        approvals_version: "v1",
      })
      .mockResolvedValueOnce({
        is_processing: true,
        has_active_subagents: false,
        current_stream: { stream_id: 9, response_ids: [2] },
        approvals_version: "v1",
      })
      .mockResolvedValue({ is_processing: false, approvals_version: "v1" });
    resumeMock.mockReturnValueOnce(
      scripted([startPacket("done"), stopPacket(), cursor(2)]),
    );
    getSessionMock.mockResolvedValue(saved([historyPacket("done")], "v1"));

    void watchBackgroundAgents("s1", SERVER_URL, client);
    await jest.advanceTimersByTimeAsync(3000);

    expect(resumeMock.mock.calls[0]?.[1]).toBe(9);
  });

  // A finished agent's unread result starts the root's turn, which the server dispatches later.
  it("follows a root turn that starts after a read reports startable input", async () => {
    await openIdle("v1");
    jest
      .mocked(getChatSessionStatus)
      .mockResolvedValueOnce({
        is_processing: false,
        has_active_subagents: false,
        has_startable_input: true,
        approvals_version: "v1",
      })
      .mockResolvedValueOnce({
        is_processing: true,
        has_active_subagents: false,
        current_stream: { stream_id: 9, response_ids: [2] },
        approvals_version: "v1",
      })
      .mockResolvedValue({ is_processing: false, approvals_version: "v1" });
    resumeMock.mockReturnValueOnce(
      scripted([startPacket("done"), stopPacket(), cursor(2)]),
    );
    getSessionMock.mockResolvedValue(saved([historyPacket("done")], "v1"));

    void watchBackgroundAgents("s1", SERVER_URL, client);
    await jest.advanceTimersByTimeAsync(3000);

    expect(resumeMock.mock.calls[0]?.[1]).toBe(9);
  });

  // A finished agent's unread result starts the root's turn after a recovery's idle read.
  it("watches startable work that a recovery's idle read reports", async () => {
    await openIdle("v1");
    useChatSessionStore.getState().updateChatState("s1", "settling");
    jest
      .mocked(getChatSessionStatus)
      .mockResolvedValueOnce({
        is_processing: false,
        has_startable_input: true,
        approvals_version: "v1",
      })
      .mockResolvedValueOnce({
        is_processing: true,
        current_stream: { stream_id: 9, response_ids: [2] },
        approvals_version: "v1",
      })
      .mockResolvedValue({ is_processing: false, approvals_version: "v1" });
    getSessionMock.mockResolvedValue(saved([historyPacket("asked")], "v1"));
    resumeMock.mockReturnValueOnce(
      scripted([startPacket("done"), stopPacket(), cursor(2)]),
    );

    void recoverChatSession(
      "s1",
      null,
      SERVER_URL,
      client,
      new AbortController(),
    );
    await jest.advanceTimersByTimeAsync(3000);

    expect(resumeMock.mock.calls[0]?.[1]).toBe(9);
  });

  it("reloads again on reopen when the user left during the last reload", async () => {
    await openIdle("v1");
    jest.mocked(getChatSessionStatus).mockResolvedValue({
      is_processing: false,
      has_active_subagents: false,
      approvals_version: "v2",
    });
    let release: (session: BackendChatSession) => void = () => {};
    getSessionMock.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          release = resolve;
        }),
    );
    const first = watchBackgroundAgents("s1", SERVER_URL, client);
    await jest.advanceTimersByTimeAsync(50);
    useChatSessionStore.setState({ currentSessionId: null });
    release(saved([historyPacket("asked"), agentRequest], "v2"));
    await first;
    expect(waitingIds()).toEqual([]);

    useChatSessionStore.setState({ currentSessionId: "s1" });
    getSessionMock.mockResolvedValue(
      saved([historyPacket("asked"), agentRequest], "v2"),
    );
    const second = watchBackgroundAgents("s1", SERVER_URL, client, false);
    await jest.advanceTimersByTimeAsync(100);
    await second;

    expect(waitingIds()).toEqual(["agent-2"]);
  });

  // With two waiting requests, the second decision can return while recovery loads history.
  it("follows a continuation that a decision queued while recovery settled", async () => {
    await openIdle("v1");
    useChatSessionStore.getState().updateChatState("s1", "settling");
    jest
      .mocked(getChatSessionStatus)
      .mockResolvedValue({ is_processing: false, approvals_version: "v1" });
    getSessionMock
      .mockImplementationOnce(async () => {
        useChatSessionStore
          .getState()
          .queueFollow("s1", { stream_id: 40, response_ids: [2] });
        return saved([historyPacket("asked")], "v1");
      })
      .mockResolvedValue(saved([historyPacket("asked done")], "v1"));
    resumeMock.mockReturnValueOnce(
      scripted([
        startPacket("asked"),
        deltaPacket(" done"),
        stopPacket(),
        cursor(3),
      ]),
    );

    void recoverChatSession(
      "s1",
      null,
      SERVER_URL,
      client,
      new AbortController(),
    );
    await jest.advanceTimersByTimeAsync(3000);

    expect(resumeMock.mock.calls[0]?.[1]).toBe(40);
    expect(
      useChatSessionStore.getState().sessions.get("s1")?.queuedFollow,
    ).toBe(null);
  });

  // A reply can start and finish between two status reads.
  it("reloads a newer response that the chat does not show", async () => {
    await openIdle("v1");
    jest.mocked(getChatSessionStatus).mockResolvedValue({
      is_processing: false,
      has_active_subagents: false,
      approvals_version: "v1",
      latest_response_id: 4,
    });
    getSessionMock.mockResolvedValue(saved([historyPacket("asked")], "v1"));

    const watch = watchBackgroundAgents("s1", SERVER_URL, client, false);
    await jest.advanceTimersByTimeAsync(100);
    await watch;

    // The baseline load and the reload.
    expect(getSessionMock).toHaveBeenCalledTimes(2);
  });

  it("releases the reader when its setup fails", async () => {
    await openIdle("v1");
    useChatSessionStore.getState().updateChatState("s1", "settling");
    // A stream that no API normalization reached.
    const malformed = { stream_id: 7 } as unknown as ChatStream;

    await recoverChatSession(
      "s1",
      malformed,
      SERVER_URL,
      client,
      new AbortController(),
    );

    expect(
      useChatSessionStore.getState().sessions.get("s1")?.abortController,
    ).toBeNull();
  });

  it("follows a stream that starts while it watches", async () => {
    seedLiveSession(null);
    jest.mocked(getChatSessionStatus).mockResolvedValueOnce({
      is_processing: true,
      has_active_subagents: false,
      current_stream: { stream_id: 9, response_ids: [2] },
    });
    resumeMock.mockReturnValueOnce(
      scripted([startPacket("done"), stopPacket(), cursor(2)]),
    );
    jest
      .mocked(getChatSessionStatus)
      .mockResolvedValue({ is_processing: false });
    getSessionMock.mockResolvedValue(saved([historyPacket("done")], "v1"));

    void watchBackgroundAgents("s1", SERVER_URL, client);
    await jest.advanceTimersByTimeAsync(3000);

    expect(resumeMock.mock.calls[0]?.[1]).toBe(9);
  });
});
