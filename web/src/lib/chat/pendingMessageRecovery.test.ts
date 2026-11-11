import { ChatSessionSharedStatus } from "@/app/app/types";
import type {
  BackendChatSession,
  BackendMessage,
  Message,
} from "@/app/app/types";
import {
  getLatestMessageChain,
  setMessageAsLatest,
} from "@/app/app/services/messageTree";
import { processRawChatHistory } from "@/app/app/services/lib";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import {
  refreshChatSession,
  settleChatSession,
} from "@/lib/chat/settleChatSession";

function savedMessage(
  id: number,
  type: "user" | "assistant",
  text: string
): BackendMessage {
  return {
    message_id: id,
    message_type: type,
    message: text,
    parent_message: id > 1 ? id - 1 : null,
    latest_child_message: null,
    research_type: null,
    rephrased_query: null,
    context_docs: null,
    time_sent: "2026-11-09T00:00:00Z",
    overridden_model: "",
    alternate_assistant_id: null,
    chat_session_id: "session",
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
}

function savedSession(
  messages: BackendMessage[],
  active: number | null
): BackendChatSession {
  return {
    chat_session_id: "session",
    description: "Chat",
    persona_id: 0,
    persona_name: "Assistant",
    messages: messages.map((message, index) => ({
      ...message,
      latest_child_message: messages[index + 1]?.message_id ?? null,
    })),
    time_created: "2026-11-09T00:00:00Z",
    time_updated: "2026-11-09T00:00:00Z",
    shared_status: ChatSessionSharedStatus.Private,
    current_temperature_override: null,
    current_reasoning_effort_override: null,
    owner_name: null,
    packets: messages
      .filter((message) => message.message_type === "assistant")
      .map(() => []),
    is_processing: active !== null,
    current_stream: active === null ? null : { stream_id: active },
  };
}

beforeEach(() => {
  useChatSessionStore.setState({ sessions: new Map(), currentSessionId: null });
  useChatSessionStore.getState().createSession("session");
});

afterEach(() => jest.restoreAllMocks());

test("completion follows a backend-started turn and streams its output before the session is idle", async () => {
  const prior = [
    savedMessage(1, "user", "First"),
    savedMessage(2, "assistant", "First answer"),
  ];
  const queued = [
    ...prior,
    savedMessage(3, "user", "Queued"),
    savedMessage(4, "assistant", ""),
  ];
  const store = useChatSessionStore.getState();
  const controller = store.sessions.get("session")!.abortController;
  store.updateSessionData("session", {
    chatState: "streaming",
    sendAcknowledged: Promise.resolve(2),
    readerFinished: Promise.resolve(),
    messageTree: processRawChatHistory(prior, [[]]),
  });
  const replayStarted = Promise.withResolvers<void>();
  const streamed = Promise.withResolvers<void>();
  const finished = Promise.withResolvers<void>();
  const unsubscribe = useChatSessionStore.subscribe((state) => {
    const session = state.sessions.get("session");
    if (
      session?.messageTree
        .get(4)
        ?.packets.some((packet) => packet.obj.type === "message_delta")
    )
      streamed.resolve();
    if (session?.chatState === "input") finished.resolve();
  });
  const output = new TransformStream<Uint8Array, Uint8Array>();
  const writer = output.writable.getWriter();
  let busy = true;
  const fetchMock = jest
    .spyOn(global, "fetch")
    .mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/status"))
        return Response.json({
          is_processing: busy,
          current_stream: busy ? { stream_id: 4 } : null,
        });
      if (url.includes("get-chat-session"))
        return Response.json(savedSession(queued, busy ? 4 : null));
      if (url.includes("resume-stream?stream_id=4&cursor=0")) {
        replayStarted.resolve();
        return new Response(output.readable);
      }
      throw new Error(`Unexpected request: ${url}`);
    });
  try {
    await settleChatSession({
      sessionId: "session",
      controller,
      errorMessage: "Check again",
      refreshHistory: false,
    });
    await replayStarted.promise;
    expect(
      useChatSessionStore.getState().sessions.get("session")?.chatState
    ).toBe("streaming");
    await writer.write(
      new TextEncoder().encode(
        [
          {
            placement: { turn_index: 0, tab_index: 0 },
            obj: { type: "message_delta", content: "Queued answer" },
          },
          { stream_id: 4, next_cursor: 1, replay_complete: true },
        ]
          .map((value) => JSON.stringify(value))
          .join("\n") + "\n"
      )
    );
    await streamed.promise;
    expect(
      useChatSessionStore.getState().sessions.get("session")?.messageTree.get(3)
        ?.message
    ).toBe("Queued");
    expect(
      useChatSessionStore.getState().sessions.get("session")?.uncaughtError
    ).toBeNull();
    busy = false;
    queued[3] = savedMessage(4, "assistant", "Queued answer");
    await writer.close();
    await finished.promise;
    expect(
      useChatSessionStore.getState().sessions.get("session")?.messageTree.get(4)
        ?.message
    ).toBe("Queued answer");
    expect(
      fetchMock.mock.calls.filter(([url]) =>
        String(url).includes("resume-stream")
      )
    ).toHaveLength(1);
  } finally {
    unsubscribe();
  }
});

test("queue refresh preserves a live response and its accepted input packets", async () => {
  const raw = [
    savedMessage(1, "user", "Question"),
    savedMessage(2, "assistant", ""),
  ];
  const tree = processRawChatHistory(raw, [[]]);
  const live: Message = {
    ...tree.get(2)!,
    replayCursor: 7,
    packets: [
      {
        placement: { turn_index: 0 },
        obj: { type: "message_delta", content: "Live" },
      },
      {
        placement: { turn_index: 1 },
        obj: { type: "user_message", id: "send", message: "Focus here" },
      },
    ],
  };
  tree.set(2, live);
  useChatSessionStore.getState().updateSessionData("session", {
    chatState: "streaming",
    messageTree: tree,
    sendAcknowledged: Promise.resolve(2),
    readerFinished: new Promise<void>(() => {}),
  });
  jest
    .spyOn(global, "fetch")
    .mockImplementation(async () => Response.json(savedSession(raw, 2)));
  await refreshChatSession("session", "Check again");
  const refreshed = useChatSessionStore
    .getState()
    .sessions.get("session")
    ?.messageTree.get(2);
  expect(refreshed?.packets).toBe(live.packets);
  expect(refreshed?.replayCursor).toBe(7);
});

test("a delayed queue refresh cannot undo a branch selection", async () => {
  const raw = [
    { ...savedMessage(1, "user", "Question"), latest_child_message: 2 },
    savedMessage(2, "assistant", "First answer"),
    { ...savedMessage(3, "assistant", "Other answer"), parent_message: 1 },
  ];
  const store = useChatSessionStore.getState();
  const tree = processRawChatHistory(raw, [[], []]);
  store.updateSessionData("session", { messageTree: tree });
  const response = Promise.withResolvers<Response>();
  jest.spyOn(global, "fetch").mockReturnValue(response.promise);
  const refreshing = refreshChatSession("session", "Check again");
  const selected = setMessageAsLatest(tree, 3);
  store.updateSessionMessageTree("session", selected);
  response.resolve(
    Response.json({ ...savedSession(raw, null), messages: raw })
  );
  await refreshing;
  expect(
    useChatSessionStore.getState().sessions.get("session")?.messageTree
  ).toBe(selected);
});

test("incognito recovery follows an unacknowledged response until idle without fetching saved content", async () => {
  jest.useFakeTimers();
  const store = useChatSessionStore.getState();
  const controller = store.sessions.get("session")!.abortController;
  const raw = [
    savedMessage(1, "user", "Private question"),
    savedMessage(2, "assistant", "Private answer"),
  ];
  const saved = savedSession(raw, null);
  const tree = processRawChatHistory(saved.messages, saved.packets);
  store.updateSessionData("session", {
    incognito: true,
    chatState: "unconfirmed",
    messageTree: tree,
    readerFinished: Promise.resolve(),
    sendAcknowledged: Promise.reject(new TypeError("Acknowledgement lost")),
  });
  let busy = true;
  const fetchMock = jest
    .spyOn(global, "fetch")
    .mockImplementation(async (input) => {
      if (!String(input).endsWith("/status"))
        throw new Error(`Unexpected request: ${input}`);
      return Response.json({
        is_processing: busy,
        current_stream: busy ? { stream_id: 2 } : null,
      });
    });
  try {
    const recovery = settleChatSession({
      sessionId: "session",
      controller,
      errorMessage: "Check again",
      mode: "recovery",
    });
    await jest.advanceTimersByTimeAsync(1000);
    expect(
      useChatSessionStore.getState().sessions.get("session")?.chatState
    ).toBe("unconfirmed");
    busy = false;
    await jest.advanceTimersByTimeAsync(1000);
    await recovery;
    const session = useChatSessionStore.getState().sessions.get("session");
    expect(session?.chatState).toBe("input");
    expect(session?.messageTree.get(2)?.message).toBe("Private answer");
    expect(session?.messageTree.get(2)?.packets.at(-1)?.obj.type).toBe("stop");
    expect(
      fetchMock.mock.calls.every(([url]) => String(url).endsWith("/status"))
    ).toBe(true);
  } finally {
    jest.useRealTimers();
  }
});

test.each(["completion", "refresh"])(
  "%s preserves loaded history and sibling responses when refreshing the latest page",
  async (operation) => {
    const history = Array.from({ length: 40 }, (_, index) =>
      savedMessage(
        index + 1,
        index % 2 ? "assistant" : "user",
        `Message ${index + 1}`
      )
    );
    const all = savedSession(history, null);
    all.messages.push({
      ...savedMessage(41, "assistant", "Alternative"),
      parent_message: 1,
    });
    all.packets.push([]);
    const local = processRawChatHistory(all.messages, all.packets);
    const temporary = local.get(10)!;
    local.delete(10);
    local.set(-10, { ...temporary, nodeId: -10 });
    local.set(9, {
      ...local.get(9)!,
      latestChildNodeId: -10,
      childrenNodeIds: [-10],
    });
    local.set(11, { ...local.get(11)!, parentNodeId: -10 });
    const page = {
      ...savedSession(history.slice(20), null),
      has_older_messages: true,
    };
    page.messages[19] = { ...page.messages[19]!, message: "Saved answer" };
    const store = useChatSessionStore.getState();
    const controller = store.sessions.get("session")!.abortController;
    store.updateSessionData("session", {
      messageTree: local,
      hasOlderMessages: false,
      chatState: "streaming",
      sendAcknowledged: Promise.resolve(40),
      readerFinished: Promise.resolve(),
    });
    jest
      .spyOn(global, "fetch")
      .mockImplementation(async (input) =>
        Response.json(
          String(input).endsWith("/status")
            ? { is_processing: false, current_stream: null }
            : page
        )
      );
    if (operation === "completion") {
      await settleChatSession({
        sessionId: "session",
        controller,
        errorMessage: "Check again",
      });
    } else {
      await refreshChatSession("session", "Check again");
    }
    const session = useChatSessionStore.getState().sessions.get("session")!;
    expect(
      getLatestMessageChain(session.messageTree).map(
        (message) => message.messageId
      )
    ).toEqual(history.map((message) => message.message_id));
    expect(session.messageTree.get(1)?.childrenNodeIds).toEqual([2, 41]);
    expect(session.messageTree.get(41)?.message).toBe("Alternative");
    expect(session.messageTree.has(-10)).toBe(false);
    expect(session.messageTree.get(40)?.message).toBe("Saved answer");
    expect(session.hasOlderMessages).toBe(false);
  }
);

test("refresh replaces loaded history when the latest page belongs to a disconnected branch", async () => {
  const previous = savedSession(
    [
      savedMessage(1, "user", "Old question"),
      savedMessage(2, "assistant", "Old answer"),
    ],
    null
  );
  const page = {
    ...savedSession(
      [
        savedMessage(51, "user", "Different branch"),
        savedMessage(52, "assistant", "New answer"),
      ],
      null
    ),
    has_older_messages: true,
  };
  useChatSessionStore.getState().updateSessionData("session", {
    messageTree: processRawChatHistory(previous.messages, previous.packets),
    hasOlderMessages: false,
  });
  jest.spyOn(global, "fetch").mockResolvedValue(Response.json(page));
  await refreshChatSession("session", "Check again");
  const session = useChatSessionStore.getState().sessions.get("session")!;
  expect(
    getLatestMessageChain(session.messageTree).map(
      (message) => message.messageId
    )
  ).toEqual([51, 52]);
  expect(session.messageTree.has(1)).toBe(false);
  expect(session.hasOlderMessages).toBe(true);
});

test("a failed refresh keeps Stop available and cannot overwrite a newer execution", async () => {
  const reader = Promise.withResolvers<void>();
  const failed = Promise.withResolvers<void>();
  const store = useChatSessionStore.getState();
  store.updateSessionData("session", {
    chatState: "streaming",
    readerFinished: reader.promise,
    sendAcknowledged: Promise.resolve(2),
  });
  jest
    .spyOn(global, "fetch")
    .mockRejectedValue(new TypeError("Connection lost"));
  jest.spyOn(console, "error").mockImplementation(() => failed.resolve());
  const refreshing = refreshChatSession("session", "Check again");
  await failed.promise;
  expect(
    useChatSessionStore.getState().sessions.get("session")?.chatState
  ).toBe("streaming");

  const nextController = new AbortController();
  store.updateSessionData("session", {
    abortController: nextController,
    readerFinished: undefined,
    sendAcknowledged: Promise.resolve(4),
    uncaughtError: null,
  });
  reader.resolve();
  await refreshing;
  expect(useChatSessionStore.getState().sessions.get("session")).toMatchObject({
    abortController: nextController,
    chatState: "streaming",
    uncaughtError: null,
  });
});
