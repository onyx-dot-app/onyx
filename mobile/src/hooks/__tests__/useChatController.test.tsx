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

import {
  createChatSession,
  getChatSession,
  nameChatSession,
  stopChatSession,
} from "@/api/chat/sessions";
import { streamChatMessage, type StreamEvent } from "@/api/chat/stream";
import { QUERY_KEYS } from "@/api/query-keys";
import {
  buildImmediateMessages,
  SYSTEM_NODE_ID,
  upsertMessages,
} from "@/chat/messageTree";
import { PacketType } from "@/chat/streamingModels";
import { useChatController } from "@/hooks/useChatController";
import { useChatSessionStore } from "@/state/chatSessionStore";

// `jest.mock` is hoisted above the imports by babel-jest, so the imports above receive the mocks.
jest.mock("expo-router", () => ({ router: { replace: jest.fn() } }));
jest.mock("@/state/session", () => ({
  useSession: (selector: (s: { serverUrl: string | null }) => unknown) =>
    selector({ serverUrl: "https://example.test" }),
}));
// Mock the transport; re-implement the trivial discriminators so we don't pull in expo/fetch.
jest.mock("@/api/chat/stream", () => ({
  streamChatMessage: jest.fn(),
  isPacket: (event: { obj?: unknown; placement?: unknown }) =>
    "obj" in event && "placement" in event,
  isMessageIdInfo: (event: { user_message_id?: unknown }) =>
    "user_message_id" in event,
  isStreamingError: (event: { error?: unknown }) => "error" in event,
}));
jest.mock("@/api/chat/sessions", () => ({
  createChatSession: jest.fn(),
  getChatSession: jest.fn(),
  nameChatSession: jest.fn(),
  stopChatSession: jest.fn(),
}));

const streamMock = streamChatMessage as unknown as Mock<
  (body: { origin: string }, signal: AbortSignal) => AsyncGenerator<StreamEvent>
>;
const createSessionMock = createChatSession as unknown as Mock<
  () => Promise<string>
>;
const getSessionMock = getChatSession as unknown as Mock<
  (id: string) => Promise<unknown>
>;
const stopSessionMock = stopChatSession as unknown as Mock<
  (id: string) => Promise<void>
>;
const nameSessionMock = nameChatSession as unknown as Mock<
  (id: string) => Promise<string>
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
const idInfo = {
  user_message_id: 10,
  reserved_assistant_message_id: 11,
} as StreamEvent;

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
    nameSessionMock.mockResolvedValue("Generated Name");
    useChatSessionStore.setState({
      currentSessionId: null,
      sessions: new Map(),
    });
  });

  // Drain the ~200ms auto-naming timer (wrapped in act so late store updates don't warn)
  // so a stray nameChatSession call can't bleed into the next test.
  afterEach(async () => {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 220));
    });
  });

  it("streams tokens into the assistant node and assigns message ids", async () => {
    useChatSessionStore.getState().ensureSession("s1");
    streamMock.mockReturnValue(
      scripted([
        startPacket("Hello"),
        deltaPacket(" world"),
        idInfo,
        endPacket(),
      ]),
    );

    const { result } = renderHook(() => useChatController("s1"), { wrapper });

    act(() => result.current.setInput("hi"));
    await act(async () => {
      await result.current.submit();
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

  it("creates a session on the first message of a new chat", async () => {
    createSessionMock.mockResolvedValue("new-session");
    streamMock.mockReturnValue(scripted([startPacket("Hi"), endPacket()]));

    const { result } = renderHook(() => useChatController(null), { wrapper });
    act(() => result.current.setInput("first message"));
    await act(async () => {
      await result.current.submit();
    });

    expect(createSessionMock).toHaveBeenCalledTimes(1);
    await waitFor(() =>
      expect(useChatSessionStore.getState().sessions.has("new-session")).toBe(
        true,
      ),
    );
    // drain the naming timer so it doesn't bleed into later tests
    await waitFor(() =>
      expect(nameSessionMock).toHaveBeenCalledWith("new-session"),
    );
  });

  it("names the new chat and refreshes the sidebar after the first response", async () => {
    createSessionMock.mockResolvedValue("new-session");
    streamMock.mockReturnValue(scripted([startPacket("Hi"), endPacket()]));

    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
    });
    const invalidateSpy = jest.spyOn(client, "invalidateQueries");
    function localWrapper({ children }: { children: React.ReactNode }) {
      return (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      );
    }

    const { result } = renderHook(() => useChatController(null), {
      wrapper: localWrapper,
    });
    act(() => result.current.setInput("hello"));
    await act(async () => {
      await result.current.submit();
    });

    await waitFor(() =>
      expect(nameSessionMock).toHaveBeenCalledWith("new-session"),
    );
    await waitFor(() =>
      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: QUERY_KEYS.chatSessions("https://example.test"),
      }),
    );
  });

  it("does not auto-name a session that already has prior messages", async () => {
    // seed s1 with a prior exchange → a real ongoing chat
    const { initialUserNode, initialAgentNode } = buildImmediateMessages(
      SYSTEM_NODE_ID,
      "earlier message",
      [],
    );
    useChatSessionStore
      .getState()
      .hydrateSession(
        "s1",
        upsertMessages(new Map(), [initialUserNode, initialAgentNode], true),
      );
    streamMock.mockReturnValue(scripted([startPacket("Hi"), endPacket()]));

    const { result } = renderHook(() => useChatController("s1"), { wrapper });
    act(() => result.current.setInput("follow up"));
    await act(async () => {
      await result.current.submit();
    });

    await waitFor(() => expect(result.current.chatState).toBe("input"));
    expect(nameSessionMock).not.toHaveBeenCalled();
  });

  it("auto-names an opened-but-empty session on its first message", async () => {
    // reopened, unnamed, no user messages yet — must still name on the first message
    useChatSessionStore.getState().ensureSession("s1");
    streamMock.mockReturnValue(scripted([startPacket("Hi"), endPacket()]));

    const { result } = renderHook(() => useChatController("s1"), { wrapper });
    act(() => result.current.setInput("hi"));
    await act(async () => {
      await result.current.submit();
    });

    await waitFor(() => expect(nameSessionMock).toHaveBeenCalledWith("s1"));
  });

  it("renders a backend streaming error on the assistant node (live)", async () => {
    useChatSessionStore.getState().ensureSession("s1");
    // root-level StreamingError over a 200, not a wrapped packet
    streamMock.mockReturnValue(
      scripted([
        { error: "Error from gpt-4o-mini: empty response" } as StreamEvent,
      ]),
    );

    const { result } = renderHook(() => useChatController("s1"), { wrapper });
    act(() => result.current.setInput("hi"));
    await act(async () => {
      await result.current.submit();
    });

    await waitFor(() => {
      const last = result.current.messages[result.current.messages.length - 1];
      expect(last?.type).toBe("error");
    });
    const errorNode = result.current.messages.find((m) => m.type === "error");
    expect(errorNode?.message).toBe("Error from gpt-4o-mini: empty response");
    await waitFor(() => expect(result.current.chatState).toBe("input"));
  });

  it("stop aborts the stream and stops the backend run", async () => {
    useChatSessionStore.getState().ensureSession("s1");
    stopSessionMock.mockResolvedValue();
    // Keeps streaming until the controller's signal is aborted.
    streamMock.mockImplementation((_body, signal) =>
      (async function* () {
        yield startPacket("Hello");
        while (!signal.aborted) {
          await new Promise((resolve) => setTimeout(resolve, 5));
          yield deltaPacket(".");
        }
      })(),
    );

    const { result } = renderHook(() => useChatController("s1"), { wrapper });
    act(() => result.current.setInput("hi"));
    await act(async () => {
      await result.current.submit();
    });
    await waitFor(() => expect(result.current.chatState).toBe("streaming"));

    act(() => result.current.stop());

    await waitFor(() => expect(result.current.chatState).toBe("input"));
    expect(stopSessionMock).toHaveBeenCalledWith("s1");
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
});
