import { ChatSessionSharedStatus } from "@/app/app/types";
import type {
  BackendChatSession,
  BackendMessage,
  Message,
} from "@/app/app/types";
import { getLatestMessageChain } from "@/app/app/services/messageTree";
import { processRawChatHistory } from "@/app/app/services/lib";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import {
  refreshChatSession,
  settleChatSession,
} from "@/lib/chat/settleChatSession";
import {
  fetchSettledChatSession,
  waitForChatResponseEnd,
} from "@/lib/chat/sessionReadiness";

const actualLib = jest.requireActual<typeof import("@/app/app/services/lib")>(
  "@/app/app/services/lib"
);
const actualReadiness = jest.requireActual<
  typeof import("@/lib/chat/sessionReadiness")
>("@/lib/chat/sessionReadiness");

jest.mock("@/app/app/services/lib", () => ({
  ...jest.requireActual("@/app/app/services/lib"),
  processRawChatHistory: jest.fn(),
}));
jest.mock("@/lib/chat/sessionReadiness", () => ({
  ...jest.requireActual("@/lib/chat/sessionReadiness"),
  fetchSettledChatSession: jest.fn(),
  waitForChatResponseEnd: jest.fn(),
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
  jest.resetAllMocks();
  useChatSessionStore.setState({ sessions: new Map(), currentSessionId: null });
  useChatSessionStore.getState().createSession("session");
});

afterEach(() => jest.restoreAllMocks());

describe("with stubbed server checks", () => {
  beforeEach(() => {
    useChatSessionStore.getState().updateSessionData("session", {
      chatState: "cancelling",
    });
    jest.mocked(waitForChatResponseEnd).mockResolvedValue(null);
    jest
      .mocked(fetchSettledChatSession)
      .mockResolvedValue(savedSession([], null));
    jest.mocked(processRawChatHistory).mockReturnValue(new Map());
  });

  function settle(mode: "completion" | "recovery" = "completion") {
    const controller = useChatSessionStore
      .getState()
      .sessions.get("session")!.abortController;
    return settleChatSession({
      sessionId: "session",
      controller,
      errorMessage,
      mode,
    });
  }

  test("explicit recovery checks server state after acknowledgement fails", async () => {
    const log = jest.spyOn(console, "error").mockImplementation(() => {});
    const acknowledgement = Promise.reject(new TypeError("Connection lost"));
    useChatSessionStore.getState().updateSessionData("session", {
      sendAcknowledged: acknowledgement,
    });
    try {
      await settle();
      expect(waitForChatResponseEnd).not.toHaveBeenCalled();
      expect(fetchSettledChatSession).not.toHaveBeenCalled();
      expect(
        useChatSessionStore.getState().sessions.get("session")
      ).toMatchObject({
        chatState: "unconfirmed",
      });

      const idle = Promise.withResolvers<number | null>();
      const polling = Promise.withResolvers<void>();
      jest.mocked(waitForChatResponseEnd).mockImplementation(() => {
        polling.resolve();
        return idle.promise;
      });
      const saved = new Map([[42, message(42, "assistant", "Saved answer")]]);
      jest.mocked(processRawChatHistory).mockReturnValue(saved);
      const recovery = settle("recovery");
      await polling.promise;
      expect(fetchSettledChatSession).not.toHaveBeenCalled();
      expect(
        useChatSessionStore.getState().sessions.get("session")?.chatState
      ).toBe("unconfirmed");

      idle.resolve(null);
      await recovery;
      expect(fetchSettledChatSession).toHaveBeenCalledWith("session");
      expect(
        useChatSessionStore.getState().sessions.get("session")
      ).toMatchObject({
        chatState: "input",
        sendAcknowledged: undefined,
        messageTree: saved,
        uncaughtError: null,
      });
    } finally {
      log.mockRestore();
    }
  });

  test("explicit recovery still waits for a pending send acknowledgement", async () => {
    const acknowledgement = Promise.withResolvers<number | null>();
    useChatSessionStore.getState().updateSessionData("session", {
      chatState: "unconfirmed",
      sendAcknowledged: acknowledgement.promise,
    });
    const recovery = settle("recovery");
    await Promise.resolve();
    expect(waitForChatResponseEnd).not.toHaveBeenCalled();
    acknowledgement.resolve(42);
    await recovery;
    expect(waitForChatResponseEnd).toHaveBeenCalledWith("session", 42);
    expect(fetchSettledChatSession).toHaveBeenCalledWith("session");
  });

  test("a rejected send without a reserved row keeps its submitted text and error", async () => {
    const user = {
      ...message(-1, "user", "Keep this question"),
      childrenNodeIds: [-2],
      latestChildNodeId: -2,
    };
    const error = {
      ...message(-2, "error", ""),
      errorMessage: "Too many requests",
      parentNodeId: -1,
    };
    const tree = new Map<number, Message>([
      [-1, user],
      [-2, error],
    ]);
    useChatSessionStore.getState().updateSessionMessageTree("session", tree);
    await settle();
    const session = useChatSessionStore.getState().sessions.get("session")!;
    expect(session.messageTree).toEqual(tree);
    expect(session.chatState).toBe("input");
  });

  test("stopping waits for saved history and preserves error retry details", async () => {
    const idle = Promise.withResolvers<number | null>();
    const history = Promise.withResolvers<BackendChatSession>();
    jest.mocked(waitForChatResponseEnd).mockReturnValue(idle.promise);
    jest.mocked(fetchSettledChatSession).mockReturnValue(history.promise);
    const failed = {
      ...message(-2, "error", "Partial answer"),
      errorMessage: "Save failed",
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
    idle.resolve(null);
    await Promise.resolve();
    expect(
      useChatSessionStore.getState().sessions.get("session")?.chatState
    ).toBe("cancelling");
    history.resolve(savedSession([], null));
    await pending;
    const session = useChatSessionStore.getState().sessions.get("session")!;
    expect(session.chatState).toBe("input");
    expect(session.messageTree.get(42)).toMatchObject({
      type: "error",
      message: "Partial answer",
      errorMessage: "Save failed",
      isRetryable: true,
      errorCode: "RESPONSE_SAVE_ERROR",
    });
  });

  test.each([
    {
      status: undefined,
      code: null,
      savedType: "assistant",
      text: "Saved answer",
      recover: true,
    },
    {
      status: undefined,
      code: "STREAM_GAP",
      savedType: "assistant",
      text: "Saved answer",
      recover: true,
    },
    {
      status: undefined,
      code: null,
      savedType: "assistant",
      text: "",
      recover: false,
    },
    {
      status: undefined,
      code: null,
      savedType: "error",
      text: "Partial answer",
      recover: true,
    },
    {
      status: undefined,
      code: "RESPONSE_SAVE_ERROR",
      savedType: "assistant",
      text: "",
      recover: false,
    },
    {
      status: undefined,
      code: "RESPONSE_SAVE_ERROR",
      savedType: "assistant",
      text: "Saved answer",
      recover: true,
    },
    ...(
      [null, "running", "suspended", "complete", "limit", "cancelled"] as const
    ).map((status) => ({
      code: "RESPONSE_SAVE_ERROR",
      savedType: "assistant" as const,
      text: "Response was terminated prior to completion, try regenerating.",
      status,
      recover:
        status === "complete" || status === "limit" || status === "cancelled",
    })),
  ] as const)(
    "recovery prefers successful saved answers and retains unresolved errors ($code, $savedType, $status, '$text')",
    async ({ code, savedType, text, recover, status }) => {
      const failed: Message = {
        ...message(-2, "error", ""),
        errorMessage: "Could not finish this response",
        messageId: 42,
        errorCode: code,
        isRetryable: true,
      };
      const saved: Message = {
        ...message(42, savedType, text),
        responseStatus: status,
        messageId: 42,
        errorMessage: savedType === "error" ? "Saved refusal" : undefined,
        packets: [
          ...(code === "RESPONSE_SAVE_ERROR"
            ? [
                {
                  placement: { turn_index: 0 },
                  obj: {
                    type: "reasoning_delta" as const,
                    reasoning: "Partial reasoning",
                  },
                },
              ]
            : []),
          { placement: { turn_index: 0 }, obj: { type: "stop" } },
        ],
      };
      useChatSessionStore.getState().updateSessionData("session", {
        chatState: "unconfirmed",
        uncaughtError: failed.errorMessage,
        messageTree: new Map([[-2, failed]]),
      });
      jest
        .mocked(processRawChatHistory)
        .mockReturnValue(new Map([[42, saved]]));
      await settle("recovery");
      const restored = useChatSessionStore
        .getState()
        .sessions.get("session")
        ?.messageTree.get(42);
      if (recover) {
        expect(restored).toBe(saved);
      } else {
        expect(restored).toMatchObject({
          type: "error",
          errorMessage: failed.errorMessage,
          errorCode: code,
          isRetryable: true,
          packets: [],
        });
      }
      expect(
        useChatSessionStore.getState().sessions.get("session")?.uncaughtError
      ).toBeNull();
    }
  );

  test("a late failed readiness check cannot change a newer request", async () => {
    const idle = Promise.withResolvers<number | null>();
    jest.mocked(waitForChatResponseEnd).mockReturnValue(idle.promise);
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

  test.each(["readiness", "history"])(
    "a failed %s check preserves output and allows a later retry",
    async (stage) => {
      const log = jest.spyOn(console, "error").mockImplementation(() => {});
      const tree = new Map([[42, message(42, "assistant", "Partial answer")]]);
      useChatSessionStore.getState().updateSessionMessageTree("session", tree);
      if (stage === "readiness") {
        jest
          .mocked(waitForChatResponseEnd)
          .mockRejectedValueOnce(new Error("Offline"));
      } else {
        jest
          .mocked(fetchSettledChatSession)
          .mockRejectedValueOnce(new Error("Offline"));
      }
      try {
        await settle();
        expect(
          useChatSessionStore.getState().sessions.get("session")
        ).toMatchObject({
          chatState: "unconfirmed",
          uncaughtError: errorMessage,
          messageTree: tree,
        });
        expect(processRawChatHistory).not.toHaveBeenCalled();

        const saved = new Map([[42, message(42, "assistant", "Saved answer")]]);
        jest.mocked(processRawChatHistory).mockReturnValue(saved);
        await settle();
        expect(
          useChatSessionStore.getState().sessions.get("session")
        ).toMatchObject({
          chatState: "input",
          uncaughtError: null,
          messageTree: saved,
        });
      } finally {
        log.mockRestore();
      }
    }
  );

  test("completion keeps incognito content when saved rows contain only usage metadata", async () => {
    const tree = new Map([
      [1, message(1, "user", "Private question")],
      [2, message(2, "assistant", "Private answer")],
      [3, message(3, "user", "Next question")],
      [4, message(4, "assistant", "Partial answer")],
    ]);
    const store = useChatSessionStore.getState();
    store.updateSessionData("session", { incognito: true, messageTree: tree });
    await settle();
    expect(waitForChatResponseEnd).toHaveBeenCalledWith("session", undefined);
    expect(fetchSettledChatSession).not.toHaveBeenCalled();
    expect(processRawChatHistory).not.toHaveBeenCalled();
    expect(
      useChatSessionStore.getState().sessions.get("session")
    ).toMatchObject({
      chatState: "input",
      messageTree: tree,
    });
  });

  test("an old rejected attempt does not hide the latest saved answer", async () => {
    const user = {
      ...message(1, "user", "Question"),
      childrenNodeIds: [-2, 42],
      latestChildNodeId: 42,
    };
    const rejected = {
      ...message(-2, "error", ""),
      errorMessage: "Rejected attempt",
      parentNodeId: 1,
    };
    const partial = {
      ...message(42, "assistant", "Partial"),
      messageId: 42,
      parentNodeId: 1,
    };
    useChatSessionStore.getState().updateSessionMessageTree(
      "session",
      new Map<number, Message>([
        [1, user],
        [-2, rejected],
        [42, partial],
      ])
    );
    const saved = new Map<number, Message>([
      [1, user],
      [42, { ...partial, message: "Complete saved answer" }],
    ]);
    jest.mocked(processRawChatHistory).mockReturnValue(saved);
    await settle();
    expect(
      useChatSessionStore.getState().sessions.get("session")?.messageTree
    ).toEqual(saved);
  });

  test.each([false, true])(
    "recovery waits for final local packets before releasing input (aborted: %s)",
    async (aborted) => {
      const reader = Promise.withResolvers<void>();
      const store = useChatSessionStore.getState();
      const controller = store.sessions.get("session")!.abortController;
      const acknowledgement = Promise.reject(new TypeError("Connection lost"));
      store.updateSessionData("session", {
        chatState: "unconfirmed",
        incognito: true,
        sendAcknowledged: acknowledgement,
        readerFinished: reader.promise,
      });
      if (aborted) controller.abort();
      const recovery = settle("recovery");
      await Promise.resolve();
      await Promise.resolve();
      expect(waitForChatResponseEnd).not.toHaveBeenCalled();
      expect(store.sessions.get("session")?.chatState).not.toBe("input");
      store.updateSessionMessageTree(
        "session",
        new Map([[42, message(42, "assistant", "Final local output")]])
      );
      reader.resolve();
      await recovery;
      expect(
        useChatSessionStore.getState().sessions.get("session")
      ).toMatchObject({
        chatState: "input",
        readerFinished: undefined,
      });
      expect(
        useChatSessionStore
          .getState()
          .sessions.get("session")
          ?.messageTree.get(42)?.message
      ).toBe("Final local output");
    }
  );

  test("an old reader finishing cannot release another request", async () => {
    const reader = Promise.withResolvers<void>();
    const store = useChatSessionStore.getState();
    const controller = store.sessions.get("session")!.abortController;
    store.updateSessionData("session", { readerFinished: reader.promise });
    const settling = settle();
    store.setAbortController("session", new AbortController());
    controller.abort();
    reader.resolve();
    await settling;
    expect(waitForChatResponseEnd).not.toHaveBeenCalled();
    expect(
      useChatSessionStore.getState().sessions.get("session")?.chatState
    ).toBe("cancelling");
  });

  test("history replacement keeps the sources panel on the selected response", async () => {
    const local = { ...message(-2, "assistant", "Answer"), messageId: 42 };
    const saved = { ...local, nodeId: 42 };
    useChatSessionStore.getState().updateSessionData("session", {
      messageTree: new Map([[-2, local]]),
      selectedNodeIdForDocDisplay: -2,
      documentSidebarVisible: true,
    });
    jest.mocked(processRawChatHistory).mockReturnValue(new Map([[42, saved]]));
    await settle();
    expect(
      useChatSessionStore.getState().sessions.get("session")
    ).toMatchObject({
      selectedNodeIdForDocDisplay: 42,
      documentSidebarVisible: true,
    });
  });
});

describe("with a scripted fetch", () => {
  beforeEach(() => {
    jest
      .mocked(processRawChatHistory)
      .mockImplementation(actualLib.processRawChatHistory);
    jest
      .mocked(fetchSettledChatSession)
      .mockImplementation(actualReadiness.fetchSettledChatSession);
    jest
      .mocked(waitForChatResponseEnd)
      .mockImplementation(actualReadiness.waitForChatResponseEnd);
  });

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
        if (url.includes("resume-stream")) {
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
        useChatSessionStore
          .getState()
          .sessions.get("session")
          ?.messageTree.get(3)?.message
      ).toBe("Queued");
      expect(
        useChatSessionStore.getState().sessions.get("session")?.uncaughtError
      ).toBeNull();
      busy = false;
      queued[3] = savedMessage(4, "assistant", "Queued answer");
      await writer.close();
      await finished.promise;
      expect(
        useChatSessionStore
          .getState()
          .sessions.get("session")
          ?.messageTree.get(4)?.message
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

  test("refresh keeps received output and its replay cursor for the running response", async () => {
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
    });
    jest.spyOn(global, "fetch").mockImplementation(async (input) => {
      if (String(input).includes("get-chat-session"))
        return Response.json(savedSession(raw, 2));
      // Leave replay pending; this test covers the tree written before it.
      return new Promise<Response>(() => {});
    });
    await refreshChatSession("session", "Check again");
    const refreshed = useChatSessionStore
      .getState()
      .sessions.get("session")
      ?.messageTree.get(2);
    expect(refreshed?.packets).toBe(live.packets);
    expect(refreshed?.replayCursor).toBe(7);
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
      expect(session?.messageTree.get(2)?.packets.at(-1)?.obj.type).toBe(
        "stop"
      );
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

  test.each([
    ["completion", "succeeds"],
    ["refresh", "succeeds"],
    ["refresh", "fails"],
  ] as const)(
    "a %s history fetch that %s after a new send starts leaves that send alone",
    async (operation, outcome) => {
      const store = useChatSessionStore.getState();
      store.updateChatState("session", "streaming");
      const session = store.sessions.get("session")!;
      const history = Promise.withResolvers<Response>();
      const started = Promise.withResolvers<void>();
      jest.spyOn(global, "fetch").mockImplementation(async (input) => {
        if (String(input).endsWith("/status"))
          return Response.json({ is_processing: false, current_stream: null });
        started.resolve();
        return history.promise;
      });
      const pending =
        operation === "refresh"
          ? refreshChatSession("session", errorMessage)
          : settleChatSession({
              sessionId: "session",
              controller: session.abortController,
              errorMessage,
            });
      await started.promise;

      const nextController = new AbortController();
      store.setAbortController("session", nextController);
      store.updateChatState("session", "loading");
      if (outcome === "succeeds") {
        history.resolve(
          Response.json(
            savedSession(
              [
                savedMessage(1, "user", "Saved"),
                savedMessage(2, "assistant", ""),
              ],
              2
            )
          )
        );
      } else {
        history.reject(new TypeError("Connection lost"));
      }
      await pending;
      expect(
        useChatSessionStore.getState().sessions.get("session")
      ).toMatchObject({
        abortController: nextController,
        chatState: "loading",
        messageTree: session.messageTree,
        uncaughtError: null,
      });
    }
  );
});
