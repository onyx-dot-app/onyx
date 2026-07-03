import { beforeEach, describe, expect, it, jest } from "@jest/globals";
import type { Mock } from "jest-mock";
import * as React from "react";
import { act, renderHook, waitFor } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import {
  createChatSession,
  getChatSession,
  renameChatSession,
  stopChatSession,
} from "@/api/chat/sessions";
import { streamChatMessage, type StreamEvent } from "@/api/chat/stream";
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
}));
jest.mock("@/api/chat/sessions", () => ({
  createChatSession: jest.fn(),
  getChatSession: jest.fn(),
  renameChatSession: jest.fn(),
  stopChatSession: jest.fn(),
}));

const streamMock = streamChatMessage as unknown as Mock<
  (body: { origin: string }, signal: AbortSignal) => AsyncGenerator<StreamEvent>
>;
const createSessionMock = createChatSession as unknown as Mock<
  (personaId?: number) => Promise<string>
>;
const getSessionMock = getChatSession as unknown as Mock<
  (id: string) => Promise<unknown>
>;
const stopSessionMock = stopChatSession as unknown as Mock<
  (id: string) => Promise<void>
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
    renameSessionMock.mockResolvedValue();
    useChatSessionStore.setState({
      currentSessionId: null,
      sessions: new Map(),
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
    // Settle the fire-and-forget auto-name timer within the test.
    await waitFor(() => expect(renameSessionMock).toHaveBeenCalled());
  });

  it("auto-names a new session once its first answer completes", async () => {
    createSessionMock.mockResolvedValue("new-session");
    streamMock.mockReturnValue(scripted([startPacket("Hi"), endPacket()]));

    const { result } = renderHook(() => useChatController(null), { wrapper });
    act(() => result.current.setInput("first message"));
    await act(async () => {
      await result.current.submit();
    });

    await waitFor(() =>
      expect(renameSessionMock).toHaveBeenCalledWith("new-session"),
    );
    expect(renameSessionMock).toHaveBeenCalledTimes(1);
  });

  it("does not auto-name a continued (existing) session", async () => {
    useChatSessionStore.getState().ensureSession("s1");
    streamMock.mockReturnValue(scripted([startPacket("Hi"), endPacket()]));

    const { result } = renderHook(() => useChatController("s1"), { wrapper });
    act(() => result.current.setInput("another message"));
    await act(async () => {
      await result.current.submit();
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

    // The hook stays bound to null; after create+navigate the store owns the new session, so drive
    // and inspect it there (mirrors stop() aborting once the screen has navigated to the new id).
    const { result } = renderHook(() => useChatController(null), { wrapper });
    act(() => result.current.setInput("first message"));
    await act(async () => {
      await result.current.submit();
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
    act(() => result.current.setInput("hello"));
    await act(async () => {
      await result.current.submit();
    });

    expect(createSessionMock).toHaveBeenCalledWith(42);
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

    expect(createSessionMock).toHaveBeenCalledWith(7);
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
