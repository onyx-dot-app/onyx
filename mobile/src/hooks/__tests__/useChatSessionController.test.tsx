import { beforeEach, describe, expect, it, jest } from "@jest/globals";
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
import { BackendChatSession, BackendMessage } from "@/chat/interfaces";
import { getMessageByMessageId } from "@/chat/messageTree";
import { Packet, PacketType } from "@/chat/streamingModels";
import { useChatSessionController } from "@/hooks/useChatSessionController";
import { useChatSessionStore } from "@/state/chatSessionStore";

const SERVER_URL = "https://example.test";

// `jest.mock` is hoisted above imports by babel-jest.
jest.mock("@/state/session", () => ({
  useSession: (selector: (s: { serverUrl: string | null }) => unknown) =>
    selector({ serverUrl: "https://example.test" }),
}));
jest.mock("@/hooks/useToast", () => ({ toast: { error: jest.fn() } }));
jest.mock("@/api/chat/stream", () => ({
  resumeChatMessage: jest.fn(),
  isPacket: (event: { obj?: unknown; placement?: unknown }) =>
    "obj" in event && "placement" in event,
  isHeartbeat: (event: { obj?: { type?: string }; type?: string }) =>
    event?.obj?.type === "chat_heartbeat" || event?.type === "chat_heartbeat",
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
    current_stream: currentRunId == null ? null : { stream_id: currentRunId },
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

  it("preserves live output and enables input when the final history request fails after idle", async () => {
    seedLiveSession(2);
    resumeMock.mockReturnValue(
      scripted([startPacket("Live answer"), endPacket()]),
    );
    getSessionMock.mockRejectedValueOnce(new Error("Request cancelled"));
    renderHook(() => useChatSessionController("s1"), { wrapper });
    await waitFor(() =>
      expect(useChatSessionStore.getState().sessions.get("s1")?.chatState).toBe(
        "input",
      ),
    );
    expect(assistantText("s1", 2)).toBe("Live answer");
    expect(
      useChatSessionStore.getState().sessions.get("s1")?.abortController,
    ).toBeNull();
    expect(toast.error).toHaveBeenCalledWith(
      "Could not refresh saved messages. Reopen this conversation to retry.",
    );
  });

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

    expect(resumeMock).toHaveBeenCalledWith("s1", 0, expect.anything());
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
        current_stream: { stream_id: 2 },
      });
    });

    await waitFor(() =>
      expect(resumeMock).toHaveBeenCalledWith("s1", 0, expect.anything()),
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
        await tail;
        yield endPacket();
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
        await tail;
        yield deltaPacket("B");
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
          await tail.promise;
        })(),
      )
      .mockReturnValueOnce(scripted([deltaPacket("second")]))
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
    const firstSignal = resumeMock.mock.calls[0]![2];
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
      errorCode: "STREAM_GAP",
      savedAnswer: "saved answer",
      retainsError: false,
    },
    { errorCode: undefined, savedAnswer: "saved answer", retainsError: false },
    { errorCode: "STREAM_GAP", savedAnswer: "", retainsError: true },
    {
      errorCode: "RESPONSE_SAVE_ERROR",
      savedAnswer: "",
      retainsError: true,
    },
    {
      errorCode: "RESPONSE_SAVE_ERROR",
      savedAnswer: "saved answer",
      retainsError: false,
    },
  ])(
    "settles error $errorCode with saved answer '$savedAnswer'",
    async ({ errorCode, savedAnswer, retainsError }) => {
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
            : message,
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

  it("does not resume when the run id has no matching assistant node", async () => {
    seedLiveSession(999);

    renderHook(() => useChatSessionController("s1"), { wrapper });

    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(resumeMock).not.toHaveBeenCalled();
  });

  it("does not clobber a send that took over during the settle-refetch", async () => {
    seedLiveSession(2);
    resumeMock.mockReturnValue(scripted([deltaPacket("resumed")]));
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
