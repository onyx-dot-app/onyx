import { act, renderHook, waitFor } from "@testing-library/react";
import { ReadonlyURLSearchParams } from "next/navigation";
import useChatSessionController from "@/hooks/useChatSessionController";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { BackendChatSession, Message } from "@/app/app/interfaces";
import {
  fetchSettledChatSession,
  waitForChatSessionIdle,
} from "@/lib/chat/sessionReadiness";
import { processRawChatHistory, resumeStream } from "@/app/app/services/lib";
import { settleChatSession } from "@/lib/chat/settleChatSession";
import { deferred } from "@tests/setup/test-utils";

jest.mock("next-intl", () => ({
  ...jest.requireActual("next-intl"),
  useTranslations: () => (key: string) =>
    key === "checkFailed"
      ? "Reload this chat before sending another message."
      : key,
}));
jest.mock("@/providers/IncognitoProvider", () => ({
  useIncognito: () => ({
    setIncognitoEnabled: jest.fn(),
    setIncognitoSessionId: jest.fn(),
  }),
}));
jest.mock("@/lib/projects/svc", () => ({
  getProjectFilesForSession: async () => [],
}));
jest.mock("@/app/app/services/lib", () => ({
  processRawChatHistory: jest.fn(),
  nameChatSession: jest.fn(),
  patchMessageToBeLatest: jest.fn(),
  resumeStream: jest.fn(),
}));
jest.mock("@/lib/chat/sessionReadiness", () => ({
  waitForChatSessionIdle: jest.fn(),
  fetchSettledChatSession: jest.fn(),
}));

function backendSession(busy: boolean): BackendChatSession {
  return {
    chat_session_id: "session",
    description: "Existing chat",
    messages: [],
    packets: [],
    is_processing: busy,
    current_stream: null,
  } as unknown as BackendChatSession;
}

function mountController() {
  return renderHook(() =>
    useChatSessionController({
      existingChatSessionId: "session",
      searchParams: new ReadonlyURLSearchParams(),
      setSelectedDocuments: jest.fn(),
      setCurrentMessageFiles: jest.fn(),
      chatSessionIdRef: { current: null },
      loadedIdSessionRef: { current: null },
      chatInputBarRef: { current: null },
      isInitialLoad: { current: true },
      submitOnLoadPerformed: { current: false },
      refreshChatSessions: jest.fn(),
      onSubmit: jest.fn(),
    })
  );
}

beforeEach(() => {
  jest.mocked(processRawChatHistory).mockImplementation(() => new Map());
  useChatSessionStore.setState({ sessions: new Map(), currentSessionId: null });
  jest.spyOn(global, "fetch").mockResolvedValue({
    ok: true,
    json: async () => backendSession(true),
  } as Response);
  jest.mocked(fetchSettledChatSession).mockResolvedValue(backendSession(false));
});

afterEach(() => {
  jest.restoreAllMocks();
  jest.clearAllMocks();
});

test("reloaded setup stays busy until execution and history are settled", async () => {
  const idle = deferred<void>();
  const history = deferred<BackendChatSession>();
  jest.mocked(waitForChatSessionIdle).mockReturnValue(idle.promise);
  jest.mocked(fetchSettledChatSession).mockReturnValue(history.promise);
  mountController();
  await waitFor(() =>
    expect(waitForChatSessionIdle).toHaveBeenCalledWith("session")
  );
  expect(
    useChatSessionStore.getState().sessions.get("session")?.chatState
  ).toBe("streaming");
  await act(async () => idle.resolve());
  expect(
    useChatSessionStore.getState().sessions.get("session")?.chatState
  ).toBe("streaming");
  await act(async () => history.resolve(backendSession(false)));
  expect(
    useChatSessionStore.getState().sessions.get("session")?.chatState
  ).toBe("input");
});

test("failed readiness keeps sends blocked with reload instructions", async () => {
  jest.spyOn(console, "error").mockImplementation(() => {});
  jest.mocked(waitForChatSessionIdle).mockRejectedValue(new Error("503"));
  mountController();
  await waitFor(() =>
    expect(
      useChatSessionStore.getState().sessions.get("session")?.chatState
    ).toBe("unconfirmed")
  );
  expect(
    useChatSessionStore.getState().sessions.get("session")?.uncaughtError
  ).toMatch(/Reload/);
  expect(fetchSettledChatSession).not.toHaveBeenCalled();
});

test("a late history refresh cannot release a newer request", async () => {
  const history = deferred<BackendChatSession>();
  jest.mocked(waitForChatSessionIdle).mockResolvedValue();
  jest.mocked(fetchSettledChatSession).mockReturnValue(history.promise);
  mountController();
  await waitFor(() => expect(fetchSettledChatSession).toHaveBeenCalled());
  act(() => {
    const store = useChatSessionStore.getState();
    store.setAbortController("session", new AbortController());
    store.updateChatState("session", "cancelling");
  });
  await act(async () => history.resolve(backendSession(false)));
  expect(
    useChatSessionStore.getState().sessions.get("session")?.chatState
  ).toBe("cancelling");
});

test("a resumed save error survives a failed readiness check and retry", async () => {
  jest.spyOn(console, "error").mockImplementation(() => {});
  const reserved: Message = {
    nodeId: 42,
    messageId: 42,
    type: "assistant",
    message: "",
    files: [],
    packets: [],
    toolCall: null,
    parentNodeId: null,
  };
  jest
    .mocked(processRawChatHistory)
    .mockImplementation(() => new Map([[42, { ...reserved }]]));
  jest.mocked(global.fetch).mockResolvedValue({
    ok: true,
    json: async () => ({
      ...backendSession(true),
      current_stream: { stream_id: 42 },
    }),
  } as Response);
  jest.mocked(resumeStream).mockImplementation(async function* () {
    yield {
      error: "Response could not be saved",
      error_code: "RESPONSE_SAVE_ERROR",
      stack_trace: "save trace",
      is_retryable: true,
    };
  });
  jest
    .mocked(waitForChatSessionIdle)
    .mockRejectedValueOnce(new Error("503"))
    .mockResolvedValue();
  mountController();
  await waitFor(() =>
    expect(
      useChatSessionStore.getState().sessions.get("session")?.chatState
    ).toBe("unconfirmed")
  );
  const session = useChatSessionStore.getState().sessions.get("session")!;
  expect(session.messageTree.get(42)).toMatchObject({
    type: "error",
    message: "Response could not be saved",
    errorCode: "RESPONSE_SAVE_ERROR",
    packets: [],
  });
  await act(async () => {
    await settleChatSession({
      sessionId: "session",
      controller: session.abortController,
      errorMessage: "Reload this chat before sending another message.",
    });
  });
  const recovered = useChatSessionStore.getState().sessions.get("session")!;
  expect(recovered.chatState).toBe("input");
  expect(recovered.queuedMessagesPaused).toBe(true);
  expect(recovered.messageTree.get(42)).toMatchObject({
    type: "error",
    message: "Response could not be saved",
    errorCode: "RESPONSE_SAVE_ERROR",
    isRetryable: true,
    stackTrace: "save trace",
    packets: [],
  });
});
