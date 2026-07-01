import { beforeEach, describe, expect, it, jest } from "@jest/globals";
import type { Mock } from "jest-mock";
import * as React from "react";
import { act, renderHook, waitFor } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { QUERY_KEYS } from "@/api/query-keys";
import { getChatSession } from "@/api/chat/sessions";
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
jest.mock("@/api/chat/stream", () => ({
  resumeChatMessage: jest.fn(),
  isPacket: (event: { obj?: unknown; placement?: unknown }) =>
    "obj" in event && "placement" in event,
  isHeartbeat: (event: { obj?: { type?: string }; type?: string }) =>
    event?.obj?.type === "chat_heartbeat" || event?.type === "chat_heartbeat",
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

// Assistant run_id 2 is in flight — a hydrated session whose assistant node is still empty.
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
    current_run: currentRunId == null ? null : { run_id: currentRunId },
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
    client = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
    });
    useChatSessionStore.setState({
      currentSessionId: null,
      sessions: new Map(),
    });
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
      current_run: null,
    });

    renderHook(() => useChatSessionController("s1"), { wrapper });

    expect(resumeMock).toHaveBeenCalledWith("s1", 0, expect.anything());
    // After the run ends we refetch and settle from the persisted snapshot.
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
      current_run: null,
    });

    renderHook(() => useChatSessionController("s1"), { wrapper });

    // No snapshot yet → nothing to resume.
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(resumeMock).not.toHaveBeenCalled();

    // The hydration fetch resolves: the observer sees current_run and re-attaches.
    act(() => {
      client.setQueryData(QUERY_KEYS.chatSession(SERVER_URL, "s1"), {
        chat_session_id: "s1",
        description: "",
        persona_id: 0,
        messages: backendMessages(""),
        packets: [[]],
        time_created: "",
        current_run: { run_id: 2 },
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
      current_run: null,
    });

    renderHook(() => useChatSessionController("s1"), { wrapper });

    // Packets render live, before the run ends / settle runs.
    await waitFor(() => expect(assistantText("s1", 2)).toBe("Hello"));
    expect(getSessionMock).not.toHaveBeenCalled();

    act(() => releaseTail());
    await waitFor(() => expect(getSessionMock).toHaveBeenCalled());
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

    // Resume streamed, then began the settle-refetch.
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
        current_run: null,
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
      current_run: null,
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
      current_run: null,
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
      current_run: null,
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
