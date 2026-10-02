import {
  CurrentMessageFIFO,
  updateCurrentMessageFIFO,
} from "@/app/app/services/currentMessageFIFO";
import { ChatSendRejectedError, sendMessage } from "@/app/app/services/lib";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { settleChatSession } from "@/lib/chat/settleChatSession";
import { stopChatSession } from "@/lib/chat/stopChatSession";
import { waitForChatSessionIdle } from "@/lib/chat/sessionReadiness";

jest.mock("@/app/app/services/lib", () => ({
  ChatSendRejectedError: class extends Error {},
  sendMessage: jest.fn(),
  processRawChatHistory: jest.fn(() => new Map()),
}));
jest.mock("@/lib/chat/sessionReadiness", () => ({
  waitForChatSessionIdle: jest.fn(),
  fetchSettledChatSession: jest.fn(async () => ({
    messages: [],
    packets: [],
    is_processing: false,
    current_stream: null,
  })),
}));

const params = {
  message: "Question",
  parentMessageId: null,
  chatSessionId: "session",
  filters: null,
};
const errorMessage = "Cannot confirm completion";
const fetchMock = jest.fn<ReturnType<typeof fetch>, Parameters<typeof fetch>>();
const originalFetch = global.fetch;

afterEach(() => {
  global.fetch = originalFetch;
});

beforeEach(() => {
  jest.clearAllMocks();
  global.fetch = fetchMock;
  fetchMock.mockResolvedValue(new Response(null, { status: 200 }));
  jest.mocked(waitForChatSessionIdle).mockResolvedValue();
  useChatSessionStore.setState({ sessions: new Map(), currentSessionId: null });
  useChatSessionStore.getState().createSession("session", {
    chatState: "loading",
    streamingStartTime: 123,
    regenerationState: { regenerating: true, finalMessageIndex: 5 },
  });
});

function dispatch() {
  const fifo = new CurrentMessageFIFO();
  useChatSessionStore.getState().updateSessionData("session", {
    sendAcknowledged: fifo.acknowledged,
  });
  return updateCurrentMessageFIFO(fifo, params);
}

test.each([false, true])(
  "Stop waits for backend admission and targets the accepted stream (multi-model: %s)",
  async (multiModel) => {
    const admitted = Promise.withResolvers<void>();
    const provider = Promise.withResolvers<void>();
    const idle = Promise.withResolvers<void>();
    const pollingStarted = Promise.withResolvers<void>();
    jest.mocked(waitForChatSessionIdle).mockImplementation(() => {
      pollingStarted.resolve();
      return idle.promise;
    });
    jest.mocked(sendMessage).mockImplementation(async function* () {
      await admitted.promise;
      yield multiModel
        ? {
            type: "multi_model_message_id_info",
            user_message_id: 11,
            responses: [
              { message_id: 12, model_name: "First" },
              { message_id: 13, model_name: "Second" },
            ],
          }
        : {
            type: "message_id_info",
            user_message_id: 11,
            reserved_assistant_message_id: 12,
          };
      await provider.promise;
    });
    const sending = dispatch();
    const stopping = stopChatSession("session", errorMessage);
    await Promise.resolve();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(waitForChatSessionIdle).not.toHaveBeenCalled();
    expect(
      useChatSessionStore.getState().sessions.get("session")?.chatState
    ).toBe("cancelling");

    admitted.resolve();
    await pollingStarted.promise;
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/chat/stop-chat-session/session?stream_id=${multiModel ? 11 : 12}`,
      expect.objectContaining({ method: "POST" })
    );
    expect(waitForChatSessionIdle).toHaveBeenCalledWith("session");
    expect(
      useChatSessionStore.getState().sessions.get("session")?.chatState
    ).toBe("cancelling");

    idle.resolve();
    await stopping;
    expect(
      useChatSessionStore.getState().sessions.get("session")
    ).toMatchObject({
      chatState: "input",
      regenerationState: null,
      streamingStartTime: undefined,
      sendAcknowledged: undefined,
    });
    provider.resolve();
    await sending;
  }
);

test("a rejected send finishes without stopping another session turn", async () => {
  jest.mocked(sendMessage).mockImplementation(async function* () {
    yield await Promise.reject(new ChatSendRejectedError("Session is busy"));
  });
  const sending = dispatch();
  await stopChatSession("session", errorMessage);
  await sending;
  expect(fetchMock).not.toHaveBeenCalled();
  expect(waitForChatSessionIdle).toHaveBeenCalledWith("session");
});

test("a connection failure before admission cannot release input through either completion path", async () => {
  const failed = Promise.withResolvers<void>();
  jest.mocked(sendMessage).mockImplementation(async function* () {
    yield await failed.promise.then(() => {
      throw new TypeError("Connection lost");
    });
  });
  const controller = useChatSessionStore
    .getState()
    .sessions.get("session")!.abortController;
  const sending = dispatch();
  const stopping = stopChatSession("session", errorMessage);
  const rejectedStop = expect(stopping).rejects.toThrow("Connection lost");
  const settling = settleChatSession({
    sessionId: "session",
    controller,
    errorMessage,
  });
  failed.resolve();
  await sending;
  await rejectedStop;
  await settling;
  expect(waitForChatSessionIdle).not.toHaveBeenCalled();
  expect(fetchMock).not.toHaveBeenCalled();
  expect(useChatSessionStore.getState().sessions.get("session")).toMatchObject({
    chatState: "unconfirmed",
    queuedMessagesPaused: true,
  });
});

test("late admission cannot stop or clear a newer request", async () => {
  const admitted = Promise.withResolvers<void>();
  jest.mocked(sendMessage).mockImplementation(async function* () {
    await admitted.promise;
    yield {
      type: "message_id_info",
      user_message_id: 11,
      reserved_assistant_message_id: 12,
    };
  });
  const sending = dispatch();
  const stopping = stopChatSession("session", errorMessage);
  const store = useChatSessionStore.getState();
  store.setAbortController("session", new AbortController());
  store.updateChatState("session", "loading");
  admitted.resolve();
  await sending;
  await stopping;
  expect(fetchMock).not.toHaveBeenCalled();
  expect(waitForChatSessionIdle).not.toHaveBeenCalled();
  expect(useChatSessionStore.getState().sessions.get("session")).toMatchObject({
    chatState: "loading",
    streamingStartTime: 123,
    regenerationState: { regenerating: true, finalMessageIndex: 5 },
    sendAcknowledged: undefined,
  });
});
