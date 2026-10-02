import { ChatSessionSharedStatus } from "@/app/app/interfaces";
import type { BackendChatSession, Message } from "@/app/app/interfaces";
import { processRawChatHistory } from "@/app/app/services/lib";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { settleChatSession } from "@/lib/chat/settleChatSession";
import {
  fetchSettledChatSession,
  waitForChatSessionIdle,
} from "@/lib/chat/sessionReadiness";

jest.mock("@/app/app/services/lib", () => ({
  processRawChatHistory: jest.fn(),
}));
jest.mock("@/lib/chat/sessionReadiness", () => ({
  fetchSettledChatSession: jest.fn(),
  waitForChatSessionIdle: jest.fn(),
}));

const errorMessage = "Check again";

function message(nodeId: number, type: Message["type"], text: string): Message {
  return {
    nodeId,
    type,
    message: text,
    files: [],
    packets: [],
    toolCall: null,
    parentNodeId: null,
  };
}

beforeEach(() => {
  jest.resetAllMocks();
  useChatSessionStore.setState({ sessions: new Map(), currentSessionId: null });
  const store = useChatSessionStore.getState();
  store.createSession("session");
  store.updateSessionData("session", {
    chatState: "cancelling",
    queuedMessagesPaused: true,
  });
  jest.mocked(waitForChatSessionIdle).mockResolvedValue();
  jest.mocked(fetchSettledChatSession).mockResolvedValue({
    chat_session_id: "session",
    description: "Existing chat",
    persona_id: 0,
    persona_name: "Assistant",
    time_created: "2026-10-02T00:00:00Z",
    time_updated: "2026-10-02T00:00:00Z",
    shared_status: ChatSessionSharedStatus.Private,
    current_temperature_override: null,
    current_reasoning_effort_override: null,
    owner_name: null,
    messages: [],
    packets: [],
    is_processing: false,
    current_stream: null,
  });
  jest.mocked(processRawChatHistory).mockReturnValue(new Map());
});

function settle() {
  const controller = useChatSessionStore
    .getState()
    .sessions.get("session")!.abortController;
  return settleChatSession({ sessionId: "session", controller, errorMessage });
}

test("a rejected send without a reserved row keeps its submitted text and error", async () => {
  const user = message(-1, "user", "Keep this question");
  const error = {
    ...message(-2, "error", "Too many requests"),
    parentNodeId: -1,
  };
  const tree = new Map([
    [-1, user],
    [-2, error],
  ]);
  useChatSessionStore.getState().updateSessionMessageTree("session", tree);
  await settle();
  const session = useChatSessionStore.getState().sessions.get("session")!;
  expect(session.messageTree).toEqual(tree);
  expect(session.chatState).toBe("input");
  expect(session.queuedMessagesPaused).toBe(true);
});

test("stopping waits for saved history and preserves error retry details", async () => {
  const idle = Promise.withResolvers<void>();
  const history = Promise.withResolvers<BackendChatSession>();
  jest.mocked(waitForChatSessionIdle).mockReturnValue(idle.promise);
  jest.mocked(fetchSettledChatSession).mockReturnValue(history.promise);
  const failed = {
    ...message(-2, "error", "Save failed"),
    messageId: 42,
    isRetryable: true,
    errorCode: "RESPONSE_SAVE_ERROR",
  };
  useChatSessionStore
    .getState()
    .updateSessionMessageTree("session", new Map([[-2, failed]]));
  jest
    .mocked(processRawChatHistory)
    .mockReturnValue(
      new Map([[42, { ...message(42, "assistant", ""), messageId: 42 }]])
    );
  const pending = settle();
  expect(fetchSettledChatSession).not.toHaveBeenCalled();
  idle.resolve();
  await Promise.resolve();
  expect(
    useChatSessionStore.getState().sessions.get("session")?.chatState
  ).toBe("cancelling");
  history.resolve({
    chat_session_id: "session",
    description: "Existing chat",
    persona_id: 0,
    persona_name: "Assistant",
    time_created: "2026-10-02T00:00:00Z",
    time_updated: "2026-10-02T00:00:00Z",
    shared_status: ChatSessionSharedStatus.Private,
    current_temperature_override: null,
    current_reasoning_effort_override: null,
    owner_name: null,
    messages: [],
    packets: [],
    is_processing: false,
    current_stream: null,
  });
  await pending;
  const session = useChatSessionStore.getState().sessions.get("session")!;
  expect(session.chatState).toBe("input");
  expect(session.messageTree.get(42)).toMatchObject({
    type: "error",
    message: "Save failed",
    isRetryable: true,
    errorCode: "RESPONSE_SAVE_ERROR",
  });
});

test("a late failed readiness check cannot change a newer request", async () => {
  const idle = Promise.withResolvers<void>();
  jest.mocked(waitForChatSessionIdle).mockReturnValue(idle.promise);
  const pending = settle();
  useChatSessionStore
    .getState()
    .setAbortController("session", new AbortController());
  idle.reject(new Error("Old request failed"));
  await pending;
  expect(
    useChatSessionStore.getState().sessions.get("session")?.chatState
  ).toBe("cancelling");
  expect(
    useChatSessionStore.getState().sessions.get("session")?.uncaughtError
  ).toBeNull();
  expect(fetchSettledChatSession).not.toHaveBeenCalled();
});
