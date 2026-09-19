import { beforeEach, describe, expect, it, jest } from "@jest/globals";
import type { Mock } from "jest-mock";
import * as React from "react";
import { act, renderHook, waitFor } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { router } from "expo-router";

import {
  createChatSession,
  getChatSession,
  renameChatSession,
  stopChatSession,
} from "@/api/chat/sessions";
import { streamChatMessage, type StreamEvent } from "@/api/chat/stream";
import { ChatFileType, type FileDescriptor } from "@/chat/interfaces";
import { PacketType, StopReason } from "@/chat/streamingModels";
import { useChatController } from "@/hooks/useChatController";
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
  isPacket: (event: { obj?: unknown; placement?: unknown }) =>
    "obj" in event && "placement" in event,
  isMessageIdInfo: (event: { user_message_id?: unknown }) =>
    "user_message_id" in event,
  isStreamError: (event: { error?: unknown }) =>
    "error" in event && typeof event.error === "string",
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
  (personaId?: number, projectId?: number | null) => Promise<string>
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
function streamError(error: string, errorCode?: string): StreamEvent {
  return { error, error_code: errorCode ?? null } as unknown as StreamEvent;
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
  });

  it("surfaces a bare backend error that arrives before any content", async () => {
    useChatSessionStore.getState().ensureSession("s1");
    streamMock.mockReturnValue(scripted([streamError("Boom.")]));

    const { result } = renderHook(() => useChatController("s1"), { wrapper });
    await act(async () => {
      await result.current.submit("hi");
    });

    await waitFor(() => expect(result.current.chatState).toBe("input"));
    const messages = result.current.messages;
    expect(messages.map((m) => m.type)).toEqual(["user", "error"]);
    expect(messages[1]!.message).toBe("Boom.");
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

  it("threads toolOptions onto the send body (deep research / tools / sources)", async () => {
    useChatSessionStore.getState().ensureSession("s-tools");
    streamMock.mockReturnValue(scripted([startPacket("Hi"), endPacket()]));

    const { result } = renderHook(() => useChatController("s-tools"), {
      wrapper,
    });
    await act(async () => {
      await result.current.submit("hi", [], undefined, {
        deepResearch: true,
        allowedToolIds: [1, 3],
        forcedToolId: 3,
        internalSearchFilters: { source_type: ["web"] },
        llmOverride: {
          model_configuration_id: 7,
          model_provider: "OpenAI Prod",
          model_version: "gpt-5",
        },
      });
    });

    await waitFor(() => expect(result.current.chatState).toBe("input"));

    const body = streamMock.mock.calls[0]![0] as unknown as {
      deep_research: boolean;
      allowed_tool_ids: number[] | null;
      forced_tool_id: number | null;
      internal_search_filters: { source_type: string[] | null } | null;
      llm_override: { model_configuration_id: number } | null;
    };
    expect(body.deep_research).toBe(true);
    expect(body.allowed_tool_ids).toEqual([1, 3]);
    expect(body.forced_tool_id).toBe(3);
    expect(body.internal_search_filters).toEqual({ source_type: ["web"] });
    expect(body.llm_override).toEqual({
      model_configuration_id: 7,
      model_provider: "OpenAI Prod",
      model_version: "gpt-5",
    });
  });

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
      allowed_tool_ids: number[] | null;
      forced_tool_id: number | null;
      internal_search_filters: unknown;
      llm_override: unknown;
    };
    expect(body.deep_research).toBe(false);
    expect(body.allowed_tool_ids).toBeNull();
    expect(body.forced_tool_id).toBeNull();
    expect(body.internal_search_filters).toBeNull();
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

  it("stop aborts the stream and stops the backend run", async () => {
    useChatSessionStore.getState().ensureSession("s1");
    stopSessionMock.mockResolvedValue();
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
    await act(async () => {
      await result.current.submit("hi");
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
});
