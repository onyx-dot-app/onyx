import {
  CurrentMessageFIFO,
  updateCurrentMessageFIFO,
} from "@/app/app/services/currentMessageFIFO";
import { ChatSendRejectedError, sendMessage } from "@/app/app/services/lib";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { settleChatSession } from "@/lib/chat/settleChatSession";
import { stopChatSession } from "@/lib/chat/stopChatSession";
import { waitForChatResponseEnd } from "@/lib/chat/sessionReadiness";

jest.mock("@/app/app/services/lib", () => ({
  ChatSendRejectedError: class extends Error {},
  sendMessage: jest.fn(),
  processRawChatHistory: jest.fn(() => new Map()),
}));
jest.mock("@/lib/chat/sessionReadiness", () => ({
  waitForChatResponseEnd: jest.fn(),
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
  jest.mocked(waitForChatResponseEnd).mockResolvedValue(null);
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
  "Stop waits for backend admission, then stops the chat's current turn (multi-model: %s)",
  async (multiModel) => {
    const admitted = Promise.withResolvers<void>();
    const provider = Promise.withResolvers<void>();
    const idle = Promise.withResolvers<number | null>();
    const pollingStarted = Promise.withResolvers<void>();
    jest.mocked(waitForChatResponseEnd).mockImplementation(() => {
      pollingStarted.resolve();
      return idle.promise;
    });
    jest.mocked(sendMessage).mockImplementation(async function* () {
      await admitted.promise;
      yield multiModel
        ? {
            user_message_id: 11,
            responses: [
              { message_id: 12, model_name: "First" },
              { message_id: 13, model_name: "Second" },
            ],
          }
        : {
            user_message_id: 11,
            reserved_assistant_message_id: 12,
          };
      await provider.promise;
    });
    const sending = dispatch();
    const stopping = stopChatSession("session", errorMessage);
    await Promise.resolve();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(waitForChatResponseEnd).not.toHaveBeenCalled();
    expect(
      useChatSessionStore.getState().sessions.get("session")?.chatState
    ).toBe("cancelling");

    admitted.resolve();
    await pollingStarted.promise;
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/chat/stop-chat-session/session",
      expect.objectContaining({ method: "POST" })
    );
    expect(waitForChatResponseEnd).toHaveBeenCalledWith(
      "session",
      multiModel ? 11 : 12
    );
    expect(
      useChatSessionStore.getState().sessions.get("session")?.chatState
    ).toBe("cancelling");

    idle.resolve(null);
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
  expect(waitForChatResponseEnd).toHaveBeenCalledWith("session", null);
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
  expect(waitForChatResponseEnd).not.toHaveBeenCalled();
  expect(fetchMock).not.toHaveBeenCalled();
  expect(useChatSessionStore.getState().sessions.get("session")).toMatchObject({
    chatState: "unconfirmed",
  });
});

test("late admission cannot stop or clear a newer request", async () => {
  const admitted = Promise.withResolvers<void>();
  jest.mocked(sendMessage).mockImplementation(async function* () {
    await admitted.promise;
    yield {
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
  expect(waitForChatResponseEnd).not.toHaveBeenCalled();
  expect(useChatSessionStore.getState().sessions.get("session")).toMatchObject({
    chatState: "loading",
    streamingStartTime: 123,
    regenerationState: { regenerating: true, finalMessageIndex: 5 },
    sendAcknowledged: undefined,
  });
});

test("a failed Stop can be sent again before the reader finishes", async () => {
  const reader = Promise.withResolvers<void>();
  useChatSessionStore.getState().updateSessionData("session", {
    chatState: "streaming",
    sendAcknowledged: Promise.resolve(42),
    readerFinished: reader.promise,
  });
  fetchMock.mockRejectedValueOnce(new TypeError("Network unavailable"));
  await expect(stopChatSession("session", errorMessage)).rejects.toThrow(
    "Network unavailable"
  );
  expect(useChatSessionStore.getState().sessions.get("session")).toMatchObject({
    chatState: "streaming",
    uncaughtError: errorMessage,
  });
  const retry = stopChatSession("session", errorMessage);
  await Promise.resolve();
  expect(fetchMock).toHaveBeenCalledTimes(2);
  expect(fetchMock).toHaveBeenLastCalledWith(
    "/api/chat/stop-chat-session/session",
    expect.objectContaining({ method: "POST" })
  );
  expect(waitForChatResponseEnd).not.toHaveBeenCalled();
  reader.resolve();
  await retry;
  expect(
    useChatSessionStore.getState().sessions.get("session")?.chatState
  ).toBe("input");
});

test("Stop after the accepted stream ended stops the queued turn that followed it", async () => {
  // The answer ended and the server started a queued turn; the browser has not
  // seen that turn yet, so the session still shows the finished stream.
  useChatSessionStore.getState().updateSessionData("session", {
    chatState: "streaming",
    sendAcknowledged: Promise.resolve(42),
    readerFinished: Promise.resolve(),
  });
  jest.mocked(waitForChatResponseEnd).mockResolvedValue(43);
  await stopChatSession("session", errorMessage);
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/chat/stop-chat-session/session",
    expect.objectContaining({ method: "POST" })
  );
  expect(fetchMock.mock.calls[0]?.[0]).not.toContain("stream_id");
});

test("Stop reaches a server turn that has not published its stream", async () => {
  // A refresh found the server preparing a queued turn: no local send and no
  // stream yet.
  useChatSessionStore.getState().updateSessionData("session", {
    chatState: "streaming",
    sendAcknowledged: undefined,
  });
  const controller = useChatSessionStore
    .getState()
    .sessions.get("session")!.abortController;
  await stopChatSession("session", errorMessage);
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/chat/stop-chat-session/session",
    expect.objectContaining({ method: "POST" })
  );
  expect(controller.signal.aborted).toBe(false);
});
