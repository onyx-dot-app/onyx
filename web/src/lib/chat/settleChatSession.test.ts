import { ChatSessionSharedStatus } from "@/app/app/types";
import type {
  BackendChatSession,
  BackendMessage,
  Message,
} from "@/app/app/types";
import { getLatestMessageChain } from "@/app/app/services/messageTree";
import { processRawChatHistory, resumeStream } from "@/app/app/services/lib";
import type { Packet } from "@/app/app/services/streamingModels";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import {
  preserveFailedMessages,
  refreshChatSession,
  settleChatSession,
} from "@/lib/chat/settleChatSession";
import { findPendingToolApprovalId } from "@/lib/chat/toolApprovals";
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
  resumeStream: jest.fn(),
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
  jest.mocked(resumeStream).mockImplementation(actualLib.resumeStream);
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
        uncaughtError: { error: failed.errorMessage ?? "" },
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
          uncaughtError: { error: errorMessage },
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

  test("refresh replays a running multi-model turn into each answer", async () => {
    const raw = [
      savedMessage(1, "user", "Question"),
      { ...savedMessage(2, "assistant", ""), model_display_name: "First" },
      {
        ...savedMessage(3, "assistant", ""),
        parent_message: 1,
        model_display_name: "Second",
      },
    ];
    const session = savedSession(raw, 1);
    session.messages[0] = { ...session.messages[0]!, latest_child_message: 3 };
    useChatSessionStore.getState().updateSessionData("session", {
      chatState: "streaming",
    });
    jest.spyOn(global, "fetch").mockImplementation(async (input) => {
      if (String(input).includes("get-chat-session"))
        return Response.json(session);
      // Leave the readiness check pending; this test covers the replay.
      return new Promise<Response>(() => {});
    });
    const approvalRequest = (modelIndex: number): Packet => ({
      placement: { turn_index: 1, tab_index: 0, model_index: modelIndex },
      obj: {
        type: "tool_approval_request",
        approval_id: `approval-${modelIndex}`,
        tool_call_id: "call",
        tool_name: "mcp__3__github__create_issue",
        display_name: "Create issue",
        arguments: {},
        expires_at: "2099-01-01T00:00:00Z",
      },
    });
    const stop: Packet = {
      placement: { turn_index: 2 },
      obj: { type: "stop" },
    };
    jest.mocked(resumeStream).mockImplementation(async function* () {
      yield approvalRequest(1);
      yield approvalRequest(0);
      yield { stream_id: 1, next_cursor: 2, replay_complete: true };
      yield stop;
      yield { stream_id: 1, next_cursor: 3, replay_complete: true };
    });

    await refreshChatSession("session", errorMessage);

    const tree = () =>
      useChatSessionStore.getState().sessions.get("session")!.messageTree;
    for (let tick = 0; tick < 50 && tree().get(1)?.replayCursor !== 3; tick++)
      await new Promise((resolve) => setTimeout(resolve, 0));
    expect(tree().get(1)?.replayCursor).toBe(3);
    expect(resumeStream).toHaveBeenCalledWith(
      "session",
      1,
      0,
      expect.anything()
    );
    expect(tree().get(2)?.packets).toEqual([approvalRequest(0), stop]);
    expect(tree().get(3)?.packets).toEqual([approvalRequest(1), stop]);
    expect(tree().get(3)?.restoredPacketCount).toBe(1);
  });

  test("a waiting approval of a lost stream stays open until its run ends", () => {
    const raw = [
      { ...savedMessage(1, "user", "Question"), latest_child_message: 2 },
      savedMessage(2, "assistant", ""),
    ];
    const local = processRawChatHistory(raw, [[]]);
    local.set(2, {
      ...local.get(2)!,
      type: "error",
      errorMessage: "network error",
      streamLost: true,
      packets: [
        {
          placement: { turn_index: 1, tab_index: 0 },
          obj: {
            type: "tool_approval_request",
            approval_id: "approval",
            tool_call_id: "call",
            tool_name: "mcp__3__github__create_issue",
            display_name: "Create issue",
            arguments: {},
            expires_at: "2099-01-01T00:00:00Z",
          },
        },
        { placement: { turn_index: 0, tab_index: 0 }, obj: { type: "stop" } },
      ],
    });
    const merged = (status: Message["responseStatus"]) => {
      const saved = processRawChatHistory(raw, [[]]);
      saved.set(2, { ...saved.get(2)!, responseStatus: status });
      return preserveFailedMessages(saved, local);
    };

    expect(findPendingToolApprovalId(merged("running"))).toBe("approval");
    expect(findPendingToolApprovalId(merged("error"))).toBeNull();
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
