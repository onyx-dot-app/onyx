import "whatwg-fetch";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { useRef } from "react";
import { ReadableStream } from "stream/web";
import { ReadonlyURLSearchParams } from "next/navigation";
import { SWRConfig } from "swr";
import useChatSessionController from "@/hooks/useChatSessionController";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import {
  BackendChatSession,
  BackendMessage,
  ChatSessionSharedStatus,
} from "@/app/app/interfaces";
import { IncognitoProvider, useIncognito } from "@/providers/IncognitoProvider";
import type { AppInputBarHandle } from "@/sections/input/AppInputBar";

jest.mock("next/navigation", () => ({
  ...jest.requireActual("next/navigation"),
  usePathname: () => "/app",
}));

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), { status });
}

function session(id: string, incognito = false): BackendChatSession {
  return {
    chat_session_id: id,
    description: id,
    persona_id: 0,
    persona_name: "",
    messages: [],
    packets: [],
    time_created: "2026-10-09T10:00:00Z",
    time_updated: "2026-10-09T10:00:00Z",
    shared_status: ChatSessionSharedStatus.Private,
    current_temperature_override: null,
    current_reasoning_effort_override: null,
    owner_name: null,
    incognito,
  };
}

function seededSession(id: string): BackendChatSession {
  const message: BackendMessage = {
    message_id: 1,
    message_type: "user",
    message: "Seeded question",
    parent_message: null,
    latest_child_message: null,
    research_type: null,
    rephrased_query: null,
    context_docs: null,
    time_sent: "2026-10-09T10:00:00Z",
    overridden_model: "",
    alternate_assistant_id: null,
    chat_session_id: id,
    citations: null,
    files: [],
    tool_call: null,
    current_feedback: null,
    sub_questions: [],
    comments: null,
    parentMessageId: null,
    refined_answer_improvement: null,
    is_agentic: null,
    preferred_response_id: null,
    model_display_name: null,
    error: null,
  };
  return { ...session(id), description: "", messages: [message] };
}

function Wrapper({ children }: { children: React.ReactNode }) {
  return (
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <IncognitoProvider>{children}</IncognitoProvider>
    </SWRConfig>
  );
}

const onSubmit = jest
  .fn<Promise<void>, [unknown]>()
  .mockResolvedValue(undefined);
const refreshChatSessions = jest.fn();

function renderController(id: string | null, query = "") {
  return renderHook(
    ({ sessionId }: { sessionId: string | null }) => {
      const controller = useChatSessionController({
        existingChatSessionId: sessionId,
        searchParams: new ReadonlyURLSearchParams(query),
        setSelectedDocuments: () => {},
        setCurrentMessageFiles: () => {},
        chatSessionIdRef: useRef<string | null>(null),
        loadedIdSessionRef: useRef<string | null>(null),
        chatInputBarRef: useRef<AppInputBarHandle | null>(null),
        isInitialLoad: useRef(true),
        submitOnLoadPerformed: useRef(false),
        refreshChatSessions,
        onSubmit,
      });
      return { ...controller, privacy: useIncognito() };
    },
    { initialProps: { sessionId: id }, wrapper: Wrapper }
  );
}

describe("chat navigation while a session loads", () => {
  let fetchSpy: jest.SpyInstance<
    ReturnType<typeof fetch>,
    Parameters<typeof fetch>
  >;
  const requests = new Map<
    string,
    ReturnType<typeof Promise.withResolvers<Response>>
  >();

  function defer(url: string) {
    const request = Promise.withResolvers<Response>();
    requests.set(url, request);
    return request;
  }

  beforeEach(() => {
    requests.clear();
    useChatSessionStore.setState({
      currentSessionId: null,
      sessions: new Map(),
    });
    fetchSpy = jest.spyOn(global, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      const request = requests.get(url);
      if (request) return request.promise;
      if (url.endsWith("/incognito-availability")) {
        return jsonResponse({ available: true });
      }
      if (url.endsWith("/files")) return jsonResponse([]);
      if (url.includes("/resume-stream?")) {
        const response = jsonResponse({});
        Object.defineProperty(response, "body", {
          value: new ReadableStream<Uint8Array>({
            start(controller) {
              controller.close();
            },
          }),
        });
        return response;
      }
      throw new Error(`Unexpected request: ${url}`);
    });
  });

  afterEach(() => {
    cleanup();
    fetchSpy.mockRestore();
  });

  it("keeps New chat empty when the old request completes", async () => {
    const oldRequest = defer("/api/chat/get-chat-session/A");
    const { result, rerender } = renderController("A");
    rerender({ sessionId: null });
    await act(async () => oldRequest.resolve(jsonResponse(session("A", true))));

    expect(useChatSessionStore.getState().currentSessionId).toBeNull();
    expect(result.current.privacy.incognitoEnabled).toBe(false);
    expect(result.current.privacy.incognitoSessionId).toBeNull();
    expect(result.current.sessionFetchError).toBeNull();
    const call = fetchSpy.mock.calls.find(([url]) =>
      String(url).endsWith("/A")
    );
    expect(call?.[1]?.signal?.aborted).toBe(true);
  });

  it("keeps the selected chat when responses arrive in reverse order", async () => {
    const requestA = defer("/api/chat/get-chat-session/A");
    const requestB = defer("/api/chat/get-chat-session/B");
    const { rerender } = renderController("A");
    rerender({ sessionId: "B" });
    await act(async () => requestB.resolve(jsonResponse(session("B"))));
    await act(async () => requestA.resolve(jsonResponse(session("A"))));

    expect(useChatSessionStore.getState().currentSessionId).toBe("B");
    expect(
      useChatSessionStore.getState().sessions.get("B")?.isFetchingChatMessages
    ).toBe(false);
  });

  it("ignores an old response body even after returning to the same chat", async () => {
    const oldBody = Promise.withResolvers<BackendChatSession>();
    const response = jsonResponse({});
    jest.spyOn(response, "json").mockImplementation(() => oldBody.promise);
    const request = defer("/api/chat/get-chat-session/A");
    const { result, rerender } = renderController("A");
    await act(async () => request.resolve(response));
    rerender({ sessionId: null });
    requests.delete("/api/chat/get-chat-session/A");
    const nextRequest = defer("/api/chat/get-chat-session/A");
    rerender({ sessionId: "A" });
    await act(async () => nextRequest.resolve(jsonResponse(session("A"))));
    await act(async () => oldBody.resolve(session("A", true)));

    expect(result.current.privacy.incognitoEnabled).toBe(false);
    expect(result.current.privacy.incognitoSessionId).toBeNull();
  });

  it.each(["network", "error body"])(
    "ignores a late %s error on New chat",
    async (failure) => {
      const request = defer("/api/chat/get-chat-session/A");
      const body = Promise.withResolvers<{ detail: string }>();
      const { result, rerender } = renderController("A");
      if (failure === "error body") {
        const response = jsonResponse({}, 403);
        jest.spyOn(response, "json").mockImplementation(() => body.promise);
        await act(async () => request.resolve(response));
      }
      rerender({ sessionId: null });
      await act(async () => {
        if (failure === "network") request.reject(new Error("Offline"));
        else body.resolve({ detail: "Access denied" });
      });

      expect(result.current.sessionFetchError).toBeNull();
      expect(useChatSessionStore.getState().currentSessionId).toBeNull();
    }
  );

  it("ignores a successful response body that rejects after cancellation", async () => {
    const request = defer("/api/chat/get-chat-session/A");
    const body = Promise.withResolvers<BackendChatSession>();
    const response = jsonResponse({});
    jest.spyOn(response, "json").mockImplementation(() => body.promise);
    const { result, rerender } = renderController("A");
    await act(async () => request.resolve(response));
    rerender({ sessionId: null });
    await act(async () =>
      body.reject(new DOMException("Aborted", "AbortError"))
    );

    expect(result.current.sessionFetchError).toBeNull();
    expect(useChatSessionStore.getState().currentSessionId).toBeNull();
  });

  it("shows a load error for an invalid current response body", async () => {
    const request = defer("/api/chat/get-chat-session/A");
    const consoleError = jest
      .spyOn(console, "error")
      .mockImplementation(() => {});
    try {
      const { result } = renderController("A");
      await act(async () => request.resolve(new Response("invalid JSON")));

      expect(result.current.sessionFetchError?.type).toBe("unknown");
      expect(
        useChatSessionStore.getState().sessions.get("A")?.isFetchingChatMessages
      ).toBe(false);
    } finally {
      consoleError.mockRestore();
    }
  });

  it("does not submit a seeded message after its project files arrive on New chat", async () => {
    const files = defer("/api/user/projects/session/A/files");
    const request = defer("/api/chat/get-chat-session/A");
    const { result, rerender } = renderController("A", "seeded=true");
    const seeded = seededSession("A");
    seeded.description = "A";
    await act(async () => request.resolve(jsonResponse(seeded)));
    await waitFor(() =>
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/user/projects/session/A/files"
      )
    );
    rerender({ sessionId: null });
    await act(async () => files.resolve(jsonResponse([{ id: "old-file" }])));

    expect(result.current.projectFiles).toEqual([]);
    expect(onSubmit).not.toHaveBeenCalled();
    expect(refreshChatSessions).not.toHaveBeenCalled();
    expect(useChatSessionStore.getState().currentSessionId).toBeNull();
  });

  it("ignores a resumed session body after opening New chat", async () => {
    const request = defer("/api/chat/get-chat-session/A");
    const { rerender } = renderController("A");
    const settledRequest = defer("/api/chat/get-chat-session/A");
    const body = Promise.withResolvers<BackendChatSession>();
    const response = jsonResponse({});
    const json = jest
      .spyOn(response, "json")
      .mockImplementation(() => body.promise);
    const runningSession = seededSession("A");
    const assistant = runningSession.messages[0];
    if (!assistant) throw new Error("Missing assistant fixture");
    assistant.message_type = "assistant";
    runningSession.description = "A";
    runningSession.current_stream = { stream_id: assistant.message_id };
    await act(async () => {
      request.resolve(jsonResponse(runningSession));
      settledRequest.resolve(response);
    });
    await waitFor(() => expect(json).toHaveBeenCalled());
    rerender({ sessionId: null });
    await act(async () => body.resolve(session("A")));

    expect(useChatSessionStore.getState().currentSessionId).toBeNull();
  });

  it("submits a seeded message while its chat remains selected", async () => {
    const request = defer("/api/chat/get-chat-session/A");
    renderController("A", "seeded=true");
    const seeded = seededSession("A");
    seeded.description = "A";
    await act(async () => request.resolve(jsonResponse(seeded)));

    expect(onSubmit).toHaveBeenCalledWith({
      message: "Seeded question",
      isSeededChat: true,
      currentMessageFiles: [],
      deepResearch: false,
    });
  });

  it("loads history and privacy for the current chat", async () => {
    const request = defer("/api/chat/get-chat-session/A");
    const { result } = renderController("A");
    await act(async () => request.resolve(jsonResponse(session("A", true))));

    expect(useChatSessionStore.getState().currentSessionId).toBe("A");
    expect(result.current.privacy.incognitoEnabled).toBe(true);
    expect(result.current.privacy.incognitoSessionId).toBe("A");
    expect(result.current.sessionFetchError).toBeNull();
  });
});
