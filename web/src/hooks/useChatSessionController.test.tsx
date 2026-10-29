import { act, renderHook, waitFor } from "@testing-library/react";
import { ReadonlyURLSearchParams } from "next/navigation";
import useChatSessionController from "@/hooks/useChatSessionController";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { BackendChatSession, Message } from "@/app/app/types";
import {
  fetchSettledChatSession,
  waitForChatSessionIdle,
} from "@/lib/chat/sessionReadiness";
import { processRawChatHistory, resumeStream } from "@/app/app/services/lib";
import { settleChatSession } from "@/lib/chat/settleChatSession";
import { stopChatSession } from "@/lib/chat/stopChatSession";
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
    yield { stream_id: 42, next_cursor: 1, replay_complete: true };
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
    errorMessage: "Response could not be saved",
    errorCode: "RESPONSE_SAVE_ERROR",
  });
  expect(session.messageTree.get(42)?.packets).toEqual([]);
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
    errorMessage: "Response could not be saved",
    errorCode: "RESPONSE_SAVE_ERROR",
    isRetryable: true,
    stackTrace: "save trace",
  });
});

test("a resumed stream keeps updating its session while another chat is selected", async () => {
  const nextPacket = deferred<void>();
  const finish = deferred<void>();
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
    await nextPacket.promise;
    yield {
      placement: { turn_index: 0, tab_index: 0 },
      obj: { type: "message_delta", content: "Research continues" },
    };
    yield { stream_id: 42, next_cursor: 1, replay_complete: true };
    await finish.promise;
  });
  jest.mocked(waitForChatSessionIdle).mockResolvedValue();
  const mounted = mountController();
  await waitFor(() => expect(resumeStream).toHaveBeenCalled());
  mounted.unmount();
  act(() => {
    const store = useChatSessionStore.getState();
    store.createSession("other-session");
    store.setCurrentSession("other-session");
  });
  await act(async () => nextPacket.resolve());
  expect(useChatSessionStore.getState().currentSessionId).toBe("other-session");
  expect(
    useChatSessionStore.getState().sessions.get("session")?.messageTree.get(42)
      ?.packetCount
  ).toBe(1);
  mountController();
  expect(resumeStream).toHaveBeenCalledTimes(1);
  await act(async () => finish.resolve());
  await waitFor(() =>
    expect(
      useChatSessionStore.getState().sessions.get("session")?.chatState
    ).toBe("input")
  );
});

test("returning after a disconnected Stop releases a now-idle session", async () => {
  const store = useChatSessionStore.getState();
  store.createSession("session");
  store.updateChatState("session", "cancelling");
  useChatSessionStore
    .getState()
    .sessions.get("session")
    ?.abortController.abort();
  jest.mocked(global.fetch).mockResolvedValue({
    ok: true,
    json: async () => backendSession(false),
  } as Response);
  jest.mocked(waitForChatSessionIdle).mockResolvedValue();
  mountController();
  await waitFor(() =>
    expect(
      useChatSessionStore.getState().sessions.get("session")?.chatState
    ).toBe("input")
  );
});

test.each([false, true])(
  "reopening an unconfirmed send recovers despite failed acknowledgement (busy: %s)",
  async (busy) => {
    const store = useChatSessionStore.getState();
    store.createSession("session");
    const acknowledgement = Promise.reject(new TypeError("Connection lost"));
    void acknowledgement.catch(() => {});
    const question: Message = {
      nodeId: 1,
      type: "user",
      message: "Keep this failed question",
      files: [],
      packets: [],
      toolCall: null,
      parentNodeId: null,
      latestChildNodeId: 2,
    };
    const failure: Message = {
      ...question,
      nodeId: 2,
      type: "error",
      message: "The send was rejected",
      parentNodeId: 1,
      latestChildNodeId: null,
      isRetryable: true,
    };
    store.updateSessionData("session", {
      chatState: "unconfirmed",
      sendAcknowledged: acknowledgement,
      messageTree: new Map([
        [1, question],
        [2, failure],
      ]),
    });
    jest.mocked(global.fetch).mockResolvedValue({
      ok: true,
      json: async () => backendSession(busy),
    } as Response);
    jest.mocked(waitForChatSessionIdle).mockResolvedValue();
    mountController();
    await waitFor(() =>
      expect(
        useChatSessionStore.getState().sessions.get("session")?.chatState
      ).toBe("input")
    );
    expect(waitForChatSessionIdle).toHaveBeenCalledWith("session");
    expect(fetchSettledChatSession).toHaveBeenCalledWith("session");
    expect(
      useChatSessionStore.getState().sessions.get("session")?.messageTree
    ).toEqual(
      new Map([
        [1, question],
        [2, failure],
      ])
    );
  }
);

test.each([
  { busy: false, aborted: false },
  { busy: true, aborted: false },
  { busy: false, aborted: true },
  { busy: true, aborted: true },
])(
  "incognito recovery preserves local content (busy: $busy, aborted: $aborted)",
  async ({ busy, aborted }) => {
    const idle = deferred<void>();
    const question: Message = {
      nodeId: 1,
      messageId: 1,
      type: "user",
      message: "Keep this private question",
      files: [],
      packets: [],
      toolCall: null,
      parentNodeId: null,
      latestChildNodeId: 2,
    };
    const answer: Message = {
      ...question,
      nodeId: 2,
      messageId: 2,
      type: "assistant",
      message: "Keep this private answer",
      parentNodeId: 1,
      latestChildNodeId: null,
    };
    const localMessages = new Map([
      [1, question],
      [2, answer],
    ]);
    const store = useChatSessionStore.getState();
    store.createSession("session", { incognito: true });
    if (aborted)
      useChatSessionStore
        .getState()
        .sessions.get("session")!
        .abortController.abort();
    store.updateSessionData("session", {
      chatState: aborted ? "streaming" : "unconfirmed",
      messageTree: localMessages,
    });
    jest.mocked(global.fetch).mockResolvedValue({
      ok: true,
      json: async () => ({ ...backendSession(busy), incognito: true }),
    } as Response);
    jest.mocked(processRawChatHistory).mockReturnValue(
      new Map([
        [1, { ...question, message: "" }],
        [2, { ...answer, message: "" }],
      ])
    );
    jest.mocked(waitForChatSessionIdle).mockReturnValue(idle.promise);
    mountController();
    await waitFor(() =>
      expect(waitForChatSessionIdle).toHaveBeenCalledWith("session")
    );
    expect(
      useChatSessionStore.getState().sessions.get("session")?.messageTree
    ).toEqual(localMessages);
    await act(async () => idle.resolve());
    const recovered = useChatSessionStore.getState().sessions.get("session")!;
    expect(recovered.chatState).toBe("input");
    expect(recovered.messageTree.get(1)).toBe(question);
    expect(recovered.messageTree.get(2)).toEqual({
      ...answer,
      packets: [
        { placement: { turn_index: 0, tab_index: 0 }, obj: { type: "stop" } },
      ],
      packetCount: 1,
    });
    expect(fetchSettledChatSession).toHaveBeenCalledWith("session");
  }
);

test("recovery replay does not mutate retained local messages", async () => {
  const finish = deferred<void>();
  const previousAnswer: Message = {
    nodeId: 42,
    messageId: 42,
    type: "assistant",
    message: "Previously displayed answer",
    files: [],
    packets: [],
    packetCount: 3,
    toolCall: null,
    parentNodeId: null,
    latestChildNodeId: 43,
  };
  const failure: Message = {
    ...previousAnswer,
    nodeId: 43,
    type: "error",
    parentNodeId: 42,
    latestChildNodeId: null,
  };
  const localMessages = new Map([
    [42, previousAnswer],
    [43, failure],
  ]);
  const store = useChatSessionStore.getState();
  store.createSession("session");
  store.updateSessionData("session", {
    chatState: "unconfirmed",
    messageTree: localMessages,
  });
  jest.mocked(global.fetch).mockResolvedValue({
    ok: true,
    json: async () => ({
      ...backendSession(true),
      current_stream: { stream_id: 42 },
    }),
  } as Response);
  jest.mocked(resumeStream).mockImplementation(async function* () {
    await finish.promise;
    yield {
      placement: { turn_index: 0, tab_index: 0 },
      obj: { type: "stop" },
    };
    yield { stream_id: 42, next_cursor: 1, replay_complete: true };
  });
  jest.mocked(waitForChatSessionIdle).mockResolvedValue();
  mountController();
  try {
    await waitFor(() => expect(resumeStream).toHaveBeenCalled());
    expect(previousAnswer.message).toBe("Previously displayed answer");
    expect(previousAnswer.packetCount).toBe(3);
    expect(localMessages.get(42)).toBe(previousAnswer);
  } finally {
    await act(async () => finish.resolve());
  }
});

test("Stop targets a reloaded multi-model stream without replay", async () => {
  const idle = deferred<void>();
  const question: Message = {
    nodeId: 41,
    messageId: 41,
    type: "user",
    message: "Compare answers",
    files: [],
    packets: [],
    toolCall: null,
    parentNodeId: null,
  };
  const responses: Message[] = [42, 43].map((id) => ({
    ...question,
    nodeId: id,
    messageId: id,
    type: "assistant",
    message: "",
    parentNodeId: question.nodeId,
  }));
  jest
    .mocked(processRawChatHistory)
    .mockImplementation(
      () =>
        new Map(
          [question, ...responses].map((message) => [message.nodeId, message])
        )
    );
  jest.mocked(global.fetch).mockResolvedValue({
    ok: true,
    json: async () => ({
      ...backendSession(true),
      current_stream: { stream_id: question.nodeId },
    }),
  } as Response);
  jest.mocked(waitForChatSessionIdle).mockReturnValue(idle.promise);
  mountController();
  await waitFor(() => expect(waitForChatSessionIdle).toHaveBeenCalled());
  expect(resumeStream).not.toHaveBeenCalled();
  const stopping = stopChatSession("session", "Check failed");
  await waitFor(() =>
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/chat/stop-chat-session/session?stream_id=41",
      expect.objectContaining({ method: "POST" })
    )
  );
  expect(
    useChatSessionStore.getState().sessions.get("session")?.chatState
  ).toBe("cancelling");
  await act(async () => {
    idle.resolve();
    await stopping;
  });
  expect(
    useChatSessionStore.getState().sessions.get("session")?.chatState
  ).toBe("input");
});

test("Stop targets the replay response and waits for its incognito tail", async () => {
  const finish = deferred<void>();
  jest.spyOn(Promise, "withResolvers").mockImplementation(() => {
    throw new Error("Promise.withResolvers is unavailable");
  });
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
    .mockImplementation(() => new Map([[42, reserved]]));
  jest.mocked(global.fetch).mockResolvedValue({
    ok: true,
    json: async () => ({
      ...backendSession(true),
      incognito: true,
      current_stream: { stream_id: 42 },
    }),
  } as Response);
  jest.mocked(resumeStream).mockImplementation(async function* () {
    await finish.promise;
    yield {
      placement: { turn_index: 0, tab_index: 0 },
      obj: { type: "message_delta", content: "Final research output" },
    };
    yield { stream_id: 42, next_cursor: 1, replay_complete: true };
  });
  jest.mocked(waitForChatSessionIdle).mockResolvedValue();
  mountController();
  await waitFor(() => expect(resumeStream).toHaveBeenCalled());
  const stopping = stopChatSession("session", "Check failed");
  await waitFor(() =>
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/chat/stop-chat-session/session?stream_id=42",
      expect.objectContaining({ method: "POST" })
    )
  );
  expect(waitForChatSessionIdle).not.toHaveBeenCalled();
  expect(
    useChatSessionStore.getState().sessions.get("session")?.chatState
  ).toBe("cancelling");
  await act(async () => {
    finish.resolve();
    await stopping;
  });
  const session = useChatSessionStore.getState().sessions.get("session");
  expect(session?.chatState).toBe("input");
  expect(session?.messageTree.get(42)?.packets).toEqual([
    expect.objectContaining({
      obj: { type: "message_delta", content: "Final research output" },
    }),
    expect.objectContaining({ obj: { type: "stop" } }),
  ]);
});

test("reopening with an aborted owner waits for its reader before recovery", async () => {
  const reader = deferred<void>();
  const store = useChatSessionStore.getState();
  store.createSession("session");
  useChatSessionStore
    .getState()
    .sessions.get("session")!
    .abortController.abort();
  const acknowledgement = Promise.reject(new TypeError("Connection lost"));
  void acknowledgement.catch(() => {});
  store.updateSessionData("session", {
    chatState: "unconfirmed",
    sendAcknowledged: acknowledgement,
    readerFinished: reader.promise,
  });
  jest.mocked(global.fetch).mockResolvedValue({
    ok: true,
    json: async () => backendSession(false),
  } as Response);
  jest.mocked(waitForChatSessionIdle).mockResolvedValue();
  mountController();
  await waitFor(() => expect(processRawChatHistory).toHaveBeenCalled());
  expect(waitForChatSessionIdle).not.toHaveBeenCalled();
  expect(
    useChatSessionStore.getState().sessions.get("session")?.chatState
  ).toBe("unconfirmed");
  await act(async () => reader.resolve());
  await waitFor(() =>
    expect(
      useChatSessionStore.getState().sessions.get("session")?.chatState
    ).toBe("input")
  );
});

test("an earlier Stop cannot release input while a replacement replay has unread packets", async () => {
  const oldReader = deferred<void>();
  const replayTail = deferred<void>();
  const store = useChatSessionStore.getState();
  store.createSession("session", { incognito: true });
  const controller = useChatSessionStore
    .getState()
    .sessions.get("session")!.abortController;
  store.updateSessionData("session", {
    chatState: "cancelling",
    sendAcknowledged: Promise.resolve(42),
    readerFinished: oldReader.promise,
  });
  const stopping = settleChatSession({
    sessionId: "session",
    controller,
    errorMessage: "Check failed",
  });
  await Promise.resolve();
  controller.abort();
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
    .mockImplementation(() => new Map([[42, reserved]]));
  jest.mocked(global.fetch).mockResolvedValue({
    ok: true,
    json: async () => ({
      ...backendSession(true),
      incognito: true,
      current_stream: { stream_id: 42 },
    }),
  } as Response);
  jest.mocked(resumeStream).mockImplementation(async function* () {
    await replayTail.promise;
    yield {
      placement: { turn_index: 0, tab_index: 0 },
      obj: { type: "message_delta", content: "Unread tail" },
    };
    yield { stream_id: 42, next_cursor: 1, replay_complete: true };
  });
  jest.mocked(waitForChatSessionIdle).mockResolvedValue();
  mountController();
  try {
    await waitFor(() => expect(resumeStream).toHaveBeenCalled());
    await act(async () => {
      oldReader.resolve();
      await stopping;
    });
    expect(waitForChatSessionIdle).not.toHaveBeenCalled();
    expect(
      useChatSessionStore.getState().sessions.get("session")?.chatState
    ).toBe("cancelling");
  } finally {
    await act(async () => replayTail.resolve());
  }
  await waitFor(() =>
    expect(
      useChatSessionStore.getState().sessions.get("session")?.chatState
    ).toBe("input")
  );
  expect(
    useChatSessionStore.getState().sessions.get("session")?.messageTree.get(42)
      ?.packets
  ).toEqual([
    expect.objectContaining({
      obj: { type: "message_delta", content: "Unread tail" },
    }),
    expect.objectContaining({ obj: { type: "stop" } }),
  ]);
});

test("restoration commits content with its cursor and retries only the retained prefix", async () => {
  jest.spyOn(console, "error").mockImplementation(() => {});
  const boundary = deferred<void>();
  const finish = deferred<void>();
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
      incognito: true,
      current_stream: { stream_id: 42 },
    }),
  } as Response);
  jest
    .mocked(waitForChatSessionIdle)
    .mockRejectedValueOnce(new Error("Offline"));
  jest.mocked(resumeStream).mockImplementationOnce(async function* () {
    yield {
      placement: { turn_index: 0, tab_index: 0 },
      obj: { type: "message_delta", content: "First" },
    };
    yield { stream_id: 42, next_cursor: 1, replay_complete: false };
    await boundary.promise;
    yield {
      placement: { turn_index: 0, tab_index: 0 },
      obj: { type: "message_delta", content: " second" },
    };
    yield { stream_id: 42, next_cursor: 2, replay_complete: true };
    yield {
      placement: { turn_index: 0, tab_index: 0 },
      obj: { type: "message_delta", content: " interrupted" },
    };
    throw new TypeError("Connection lost before cursor");
  });
  const firstMount = mountController();
  try {
    await waitFor(() => expect(resumeStream).toHaveBeenCalled());
    expect(
      useChatSessionStore
        .getState()
        .sessions.get("session")
        ?.messageTree.get(42)?.packets
    ).toEqual([]);
    await act(async () => boundary.resolve());
    await waitFor(() =>
      expect(
        useChatSessionStore.getState().sessions.get("session")?.chatState
      ).toBe("unconfirmed")
    );
    const retained = useChatSessionStore
      .getState()
      .sessions.get("session")!
      .messageTree.get(42)!;
    expect(retained).toMatchObject({
      replayCursor: 2,
      restoredPacketCount: 2,
      packetCount: 2,
    });
    expect(retained.packets.map((packet) => packet.obj)).toEqual([
      { type: "message_delta", content: "First" },
      { type: "message_delta", content: " second" },
    ]);
  } finally {
    firstMount.unmount();
    boundary.resolve();
  }
  jest.mocked(waitForChatSessionIdle).mockResolvedValue();
  jest.mocked(resumeStream).mockImplementationOnce(async function* () {
    yield {
      placement: { turn_index: 0, tab_index: 0 },
      obj: { type: "message_delta", content: " interrupted" },
    };
    yield { stream_id: 42, next_cursor: 3, replay_complete: true };
    await finish.promise;
  });
  const secondMount = mountController();
  try {
    await waitFor(() =>
      expect(resumeStream).toHaveBeenLastCalledWith(
        "session",
        42,
        2,
        expect.any(AbortSignal)
      )
    );
    const resumed = useChatSessionStore
      .getState()
      .sessions.get("session")!
      .messageTree.get(42)!;
    expect(resumed).toMatchObject({ replayCursor: 3, packetCount: 3 });
    expect(resumed.packets.at(-1)?.obj).toEqual({
      type: "message_delta",
      content: " interrupted",
    });
  } finally {
    await act(async () => finish.resolve());
    secondMount.unmount();
  }
});

test.each([false, true])(
  "interrupted initial restoration retains its acknowledged prefix (network error: %s)",
  async (networkError) => {
    jest.spyOn(console, "error").mockImplementation(() => {});
    const idle = deferred<void>();
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
        incognito: true,
        current_stream: { stream_id: 42 },
      }),
    } as Response);
    jest.mocked(waitForChatSessionIdle).mockReturnValue(idle.promise);
    jest.mocked(resumeStream).mockImplementationOnce(async function* () {
      yield {
        placement: { turn_index: 0 },
        obj: { type: "message_delta", content: "Retained answer" },
      };
      yield { stream_id: 42, next_cursor: 1, replay_complete: false };
      yield {
        placement: { turn_index: 0 },
        obj: { type: "message_delta", content: "Unacknowledged tail" },
      };
      yield {
        error: "Unacknowledged error",
        stack_trace: "Unacknowledged trace",
        is_retryable: true,
      };
      if (networkError) throw new TypeError("Connection lost");
    });
    const view = mountController();
    try {
      await waitFor(() => expect(waitForChatSessionIdle).toHaveBeenCalled());
      const retained = useChatSessionStore
        .getState()
        .sessions.get("session")!
        .messageTree.get(42)!;
      expect(retained).toMatchObject({
        type: "assistant",
        replayCursor: 1,
        restoredPacketCount: 1,
        packetCount: 1,
      });
      expect(retained.errorMessage).toBeUndefined();
      expect(retained.packets.map((packet) => packet.obj)).toEqual([
        { type: "message_delta", content: "Retained answer" },
      ]);
      await act(async () => idle.resolve());
      const settled = useChatSessionStore.getState().sessions.get("session")!;
      expect(settled.chatState).toBe("input");
      expect(
        settled.messageTree.get(42)?.packets.map((packet) => packet.obj)
      ).toEqual([
        { type: "message_delta", content: "Retained answer" },
        { type: "stop" },
      ]);
    } finally {
      await act(async () => idle.resolve());
      view.unmount();
    }
  }
);

test.each([false, true])(
  "incognito failures close existing display content only after confirmed idle (content: %s)",
  async (hasContent) => {
    const idle = deferred<void>();
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
        incognito: true,
        current_stream: { stream_id: 42 },
      }),
    } as Response);
    jest.mocked(waitForChatSessionIdle).mockReturnValue(idle.promise);
    jest.mocked(resumeStream).mockImplementationOnce(async function* () {
      if (hasContent)
        yield {
          placement: { turn_index: 0 },
          obj: { type: "search_tool_start", is_internet_search: false },
        };
      yield {
        error: "Save failed",
        stack_trace: "Save failure trace",
        error_code: "RESPONSE_SAVE_ERROR",
        is_retryable: true,
      };
      yield { stream_id: 42, next_cursor: 1, replay_complete: true };
    });
    const view = mountController();
    try {
      await waitFor(() => expect(waitForChatSessionIdle).toHaveBeenCalled());
      const before = useChatSessionStore.getState().sessions.get("session")!;
      expect(before.chatState).toBe("streaming");
      expect(
        before.messageTree
          .get(42)
          ?.packets.some((packet) => packet.obj.type === "stop")
      ).toBe(false);
      await act(async () => idle.resolve());
      const after = useChatSessionStore.getState().sessions.get("session")!;
      expect(after.chatState).toBe("input");
      expect(after.messageTree.get(42)).toMatchObject({
        type: "error",
        errorMessage: "Save failed",
        errorCode: "RESPONSE_SAVE_ERROR",
        isRetryable: true,
      });
      if (hasContent) {
        expect(
          after.messageTree.get(42)?.packets.map((packet) => packet.obj)
        ).toEqual([
          { type: "search_tool_start", is_internet_search: false },
          { type: "stop" },
        ]);
      } else {
        expect(after.messageTree.get(42)?.packets).toEqual([]);
      }
    } finally {
      await act(async () => idle.resolve());
      view.unmount();
    }
  }
);

test.each([false, true])(
  "old initial history cannot adopt a new send owner (body pending: %s)",
  async (bodyPending) => {
    const response = deferred<Response>();
    const body = deferred<BackendChatSession>();
    jest.mocked(global.fetch).mockReturnValue(response.promise);
    mountController();
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    if (bodyPending) {
      await act(async () =>
        response.resolve({ ok: true, json: () => body.promise } as Response)
      );
    }
    const controller = new AbortController();
    const acknowledgement = Promise.resolve(99);
    const reader = Promise.resolve();
    const tree = new Map<number, Message>();
    act(() =>
      useChatSessionStore.getState().updateSessionData("session", {
        abortController: controller,
        chatState: "streaming",
        sendAcknowledged: acknowledgement,
        readerFinished: reader,
        messageTree: tree,
      })
    );
    const stale = {
      ...backendSession(true),
      current_stream: { stream_id: 42 },
    } as BackendChatSession;
    await act(async () => {
      if (bodyPending) body.resolve(stale);
      else response.resolve({ ok: true, json: async () => stale } as Response);
    });
    const current = useChatSessionStore.getState().sessions.get("session")!;
    expect(current.sendAcknowledged).toBe(acknowledgement);
    expect(current.readerFinished).toBe(reader);
    expect(current.messageTree).toBe(tree);
    expect(resumeStream).not.toHaveBeenCalled();
    expect(processRawChatHistory).not.toHaveBeenCalled();
  }
);
