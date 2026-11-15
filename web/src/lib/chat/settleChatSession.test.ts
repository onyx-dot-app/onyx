import { ChatSessionSharedStatus } from "@/app/app/types";
import type {
  BackendChatSession,
  BackendMessage,
  ChatStream,
  Message,
} from "@/app/app/types";
import { getLatestMessageChain } from "@/app/app/services/messageTree";
import { processRawChatHistory, resumeStream } from "@/app/app/services/lib";
import { type Packet, StopReason } from "@/app/app/services/streamingModels";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import {
  claimStreamReader,
  followChatSession,
  followChatStream,
  preserveFailedMessages,
  refreshChatSession,
  releaseStreamReader,
  settleChatSession,
  writesAnswer,
} from "@/lib/chat/settleChatSession";
import {
  readWaitingToolApprovals,
  useToolApprovalUi,
} from "@/lib/chat/toolApprovals";
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
  // Status checks run without real waits between them.
  CHAT_STATUS_POLL_MS: 0,
  fetchSettledChatSession: jest.fn(),
  waitForChatResponseEnd: jest.fn(),
}));

const errorMessage = "Check again";

function stream(streamId: number, responseIds = [streamId]): ChatStream {
  return { stream_id: streamId, response_ids: responseIds };
}

/**
 * Retries an assertion until it passes, like Testing Library's `waitFor`,
 * which needs a DOM. This suite runs in Node for its streaming fetch.
 */
async function waitFor(assertion: () => void, timeoutMs = 3000) {
  const deadline = Date.now() + timeoutMs;
  while (true) {
    try {
      assertion();
      return;
    } catch (error) {
      if (Date.now() > deadline) throw error;
    }
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
}

function waitingApprovalIds(): string[] {
  return readWaitingToolApprovals(
    useChatSessionStore.getState().sessions.get("session")!.messageTree
  ).map(({ request }) => request.approval_id);
}

function approvalRequest(approvalId: string, modelIndex?: number): Packet {
  return {
    placement: { turn_index: 1, tab_index: 0, model_index: modelIndex },
    obj: {
      type: "tool_approval_request",
      approval_id: approvalId,
      tool_call_id: "call",
      tool_name: "mcp__3__github__create_issue",
      display_name: "Create issue",
      arguments: {},
      agent_name: null,
    },
  };
}

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
  active: ChatStream | null
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
    current_stream: active,
  };
}

beforeEach(() => {
  jest.resetAllMocks();
  jest.mocked(resumeStream).mockImplementation(actualLib.resumeStream);
  useChatSessionStore.setState({ sessions: new Map(), currentSessionId: null });
  useChatSessionStore.getState().createSession("session");
  useToolApprovalUi.setState({ localStatuses: new Map(), nudge: null });
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

      const idle = Promise.withResolvers<null>();
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
    const acknowledgement = Promise.withResolvers<ChatStream | null>();
    useChatSessionStore.getState().updateSessionData("session", {
      chatState: "unconfirmed",
      sendAcknowledged: acknowledgement.promise,
    });
    const recovery = settle("recovery");
    await Promise.resolve();
    expect(waitForChatResponseEnd).not.toHaveBeenCalled();
    acknowledgement.resolve(stream(42));
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
    const idle = Promise.withResolvers<null>();
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
        status === "complete" ||
        status === "limit" ||
        status === "cancelled" ||
        status === "suspended",
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
    const idle = Promise.withResolvers<null>();
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

  test("confirmed idle closes every lost answer of an incognito multi-model turn", async () => {
    const lostAnswer = (nodeId: number, model: string): Message => ({
      ...message(nodeId, "error", ""),
      parentNodeId: 1,
      modelDisplayName: model,
      errorMessage: "network error",
      streamLost: true,
      packets: [
        { placement: { turn_index: 0, tab_index: 0 }, obj: { type: "stop" } },
      ],
    });
    const tree = new Map<number, Message>([
      [
        1,
        {
          ...message(1, "user", "Question"),
          childrenNodeIds: [2, 3],
          latestChildNodeId: 3,
        },
      ],
      [2, lostAnswer(2, "First")],
      [3, lostAnswer(3, "Second")],
    ]);
    useChatSessionStore.getState().updateSessionData("session", {
      incognito: true,
      messageTree: tree,
    });

    await settle();

    const settled = useChatSessionStore.getState().sessions.get("session")!;
    expect(settled.chatState).toBe("input");
    expect(settled.messageTree.get(2)?.streamLost).toBeUndefined();
    expect(settled.messageTree.get(3)?.streamLost).toBeUndefined();
  });

  test("incognito follows its approved answer's continuation in a later stream", async () => {
    const tree = new Map<number, Message>([
      [1, message(1, "user", "Private question")],
      [
        2,
        {
          ...message(2, "assistant", ""),
          messageId: 72,
          parentNodeId: 1,
          packets: [approvalRequest("approval")],
        },
      ],
    ]);
    useChatSessionStore.getState().updateSessionData("session", {
      chatState: "streaming",
      incognito: true,
      messageTree: tree,
    });
    // Another answer's turn held the chat; the decided answer continues next.
    jest
      .mocked(waitForChatResponseEnd)
      .mockResolvedValueOnce(stream(970, [72]))
      .mockResolvedValue(null);
    const answerText: Packet = {
      placement: { turn_index: 2 },
      obj: { type: "message_delta", content: "Created the issue." },
    };
    jest.mocked(resumeStream).mockImplementation(async function* () {
      yield answerText;
      yield { placement: { turn_index: 2 }, obj: { type: "stop" } };
      yield { stream_id: 970, next_cursor: 2, replay_complete: true };
    });

    await settle();

    expect(resumeStream).toHaveBeenCalledWith(
      "session",
      970,
      0,
      expect.anything()
    );
    await waitFor(() =>
      expect(
        useChatSessionStore.getState().sessions.get("session")
      ).toMatchObject({ chatState: "input" })
    );
    const answer = useChatSessionStore
      .getState()
      .sessions.get("session")!
      .messageTree.get(2)!;
    expect(answer.packets).toContainEqual(answerText);
    expect(fetchSettledChatSession).not.toHaveBeenCalled();
  });

  test("a stopping incognito chat waits through its answer's continuation and releases input", async () => {
    const tree = new Map<number, Message>([
      [1, message(1, "user", "Private question")],
      [
        2,
        {
          ...message(2, "assistant", ""),
          messageId: 72,
          parentNodeId: 1,
          packets: [approvalRequest("approval")],
        },
      ],
    ]);
    useChatSessionStore.getState().updateSessionData("session", {
      chatState: "cancelling",
      incognito: true,
      messageTree: tree,
    });
    jest
      .mocked(waitForChatResponseEnd)
      .mockResolvedValueOnce(stream(971, [72]))
      .mockResolvedValue(null);

    await settle();

    expect(resumeStream).not.toHaveBeenCalled();
    expect(waitForChatResponseEnd).toHaveBeenLastCalledWith("session", 971);
    expect(
      useChatSessionStore.getState().sessions.get("session")
    ).toMatchObject({ chatState: "input" });
  });

  test("a named stream without rows here leaves the chat as it was", () => {
    useChatSessionStore.getState().updateSessionData("session", {
      chatState: "input",
      messageTree: new Map([[1, message(1, "user", "Question")]]),
    });

    followChatStream("session", stream(972, [73]), errorMessage);

    expect(
      useChatSessionStore.getState().sessions.get("session")?.chatState
    ).toBe("input");
    expect(resumeStream).not.toHaveBeenCalled();
  });

  test("incognito shows a parked answer's saved waiting request after its stream dropped", async () => {
    const lost: Message = {
      ...message(2, "error", ""),
      messageId: 75,
      parentNodeId: 1,
      errorMessage: "network error",
      streamLost: true,
    };
    useChatSessionStore.getState().updateSessionData("session", {
      chatState: "unconfirmed",
      incognito: true,
      messageTree: new Map<number, Message>([
        [
          1,
          {
            ...message(1, "user", "Private question"),
            childrenNodeIds: [2],
            latestChildNodeId: 2,
          },
        ],
        [2, lost],
      ]),
    });
    jest.mocked(processRawChatHistory).mockReturnValue(
      new Map([
        [
          9,
          {
            ...message(9, "assistant", ""),
            messageId: 75,
            responseStatus: "suspended" as const,
            packets: [approvalRequest("parked")],
          },
        ],
      ])
    );

    await settle("recovery");

    const settled = useChatSessionStore.getState().sessions.get("session")!;
    expect(settled.chatState).toBe("input");
    expect(settled.messageTree.get(2)).toMatchObject({
      nodeId: 2,
      parentNodeId: 1,
      type: "assistant",
    });
    expect(waitingApprovalIds()).toEqual(["parked"]);
  });

  test("incognito reads the saved answer of a named continuation that ended before it could be read", async () => {
    const asked = approvalRequest("approval");
    const waited: Packet = {
      placement: { turn_index: 0, tab_index: 0 },
      obj: { type: "stop", stop_reason: StopReason.AWAITING_APPROVAL },
    };
    const finalText: Packet = {
      placement: { turn_index: 2, tab_index: 0 },
      obj: { type: "message_delta", content: "Created the issue." },
    };
    const store = useChatSessionStore.getState();
    const controller = store.sessions.get("session")!.abortController;
    store.updateSessionData("session", {
      chatState: "streaming",
      incognito: true,
      sendAcknowledged: Promise.resolve(stream(990, [77])),
      readerFinished: Promise.resolve(),
      messageTree: new Map<number, Message>([
        [
          1,
          {
            ...message(1, "user", "Private question"),
            childrenNodeIds: [2],
            latestChildNodeId: 2,
          },
        ],
        [
          2,
          {
            ...message(2, "assistant", ""),
            messageId: 77,
            parentNodeId: 1,
            packets: [asked, waited],
          },
        ],
      ]),
    });
    jest.mocked(processRawChatHistory).mockReturnValue(
      new Map([
        [
          9,
          {
            ...message(9, "assistant", "Created the issue."),
            messageId: 77,
            responseStatus: "complete" as const,
            packets: [asked, finalText],
          },
        ],
      ])
    );

    await settleChatSession({
      sessionId: "session",
      controller,
      errorMessage,
      streamUnavailable: true,
    });

    const settled = useChatSessionStore.getState().sessions.get("session")!;
    expect(settled.chatState).toBe("input");
    expect(settled.messageTree.get(2)).toMatchObject({
      nodeId: 2,
      parentNodeId: 1,
      packets: [asked, finalText],
    });
  });

  test("incognito reads the saved answer of a continuation whose resume failed before its first batch", async () => {
    const asked = approvalRequest("approval");
    const waited: Packet = {
      placement: { turn_index: 0, tab_index: 0 },
      obj: { type: "stop", stop_reason: StopReason.AWAITING_APPROVAL },
    };
    const finalText: Packet = {
      placement: { turn_index: 2, tab_index: 0 },
      obj: { type: "message_delta", content: "Created the issue." },
    };
    jest.spyOn(console, "error").mockImplementation(() => {});
    useChatSessionStore.getState().updateSessionData("session", {
      chatState: "input",
      incognito: true,
      messageTree: new Map<number, Message>([
        [
          1,
          {
            ...message(1, "user", "Private question"),
            childrenNodeIds: [2],
            latestChildNodeId: 2,
          },
        ],
        [
          2,
          {
            ...message(2, "assistant", ""),
            messageId: 78,
            parentNodeId: 1,
            packets: [asked, waited],
          },
        ],
      ]),
    });
    // The resume request fails before its first batch.
    jest
      .spyOn(global, "fetch")
      .mockResolvedValue(
        Response.json({ detail: "Service unavailable" }, { status: 503 })
      );
    jest.mocked(processRawChatHistory).mockReturnValue(
      new Map([
        [
          9,
          {
            ...message(9, "assistant", "Created the issue."),
            messageId: 78,
            responseStatus: "complete" as const,
            packets: [asked, finalText],
          },
        ],
      ])
    );

    followChatStream("session", stream(991, [78]), errorMessage);

    await waitFor(() =>
      expect(
        useChatSessionStore.getState().sessions.get("session")
      ).toMatchObject({ chatState: "input" })
    );
    await waitFor(() =>
      expect(
        useChatSessionStore
          .getState()
          .sessions.get("session")!
          .messageTree.get(2)?.packets
      ).toEqual([asked, finalText])
    );
  });

  test("incognito reads the saved answer of a continuation that dropped after only its first cursor", async () => {
    const asked = approvalRequest("approval");
    const waited: Packet = {
      placement: { turn_index: 0, tab_index: 0 },
      obj: { type: "stop", stop_reason: StopReason.AWAITING_APPROVAL },
    };
    const finalText: Packet = {
      placement: { turn_index: 2, tab_index: 0 },
      obj: { type: "message_delta", content: "Created the issue." },
    };
    jest.spyOn(console, "error").mockImplementation(() => {});
    useChatSessionStore.getState().updateSessionData("session", {
      chatState: "input",
      incognito: true,
      messageTree: new Map<number, Message>([
        [
          1,
          {
            ...message(1, "user", "Private question"),
            childrenNodeIds: [2],
            latestChildNodeId: 2,
          },
        ],
        [
          2,
          {
            ...message(2, "assistant", ""),
            messageId: 81,
            parentNodeId: 1,
            packets: [asked, waited],
          },
        ],
      ]),
    });
    jest.mocked(resumeStream).mockImplementation(async function* () {
      yield { stream_id: 995, next_cursor: 0, replay_complete: false };
      throw new TypeError("network error");
    });
    // The continuation ended on the server.
    jest
      .spyOn(global, "fetch")
      .mockImplementation(async () =>
        Response.json({ is_processing: false, current_stream: null })
      );
    jest.mocked(processRawChatHistory).mockReturnValue(
      new Map([
        [
          9,
          {
            ...message(9, "assistant", "Created the issue."),
            messageId: 81,
            responseStatus: "complete" as const,
            packets: [asked, finalText],
          },
        ],
      ])
    );

    followChatStream("session", stream(995, [81]), errorMessage);

    await waitFor(() =>
      expect(
        useChatSessionStore.getState().sessions.get("session")
      ).toMatchObject({ chatState: "input" })
    );
    await waitFor(() =>
      expect(
        useChatSessionStore
          .getState()
          .sessions.get("session")!
          .messageTree.get(2)?.packets
      ).toEqual([asked, finalText])
    );
  });

  test("a refresh in flight when a continuation takes over does not apply", async () => {
    const asked = approvalRequest("approval");
    const continued: Packet = {
      placement: { turn_index: 2, tab_index: 0 },
      obj: { type: "message_delta", content: "Continued" },
    };
    const answer: Message = {
      ...message(2, "assistant", ""),
      messageId: 82,
      parentNodeId: 1,
      packets: [asked],
    };
    useChatSessionStore.getState().updateSessionData("session", {
      chatState: "input",
      messageTree: new Map<number, Message>([
        [
          1,
          {
            ...message(1, "user", "Question"),
            childrenNodeIds: [2],
            latestChildNodeId: 2,
          },
        ],
        [2, answer],
      ]),
    });
    const page = Promise.withResolvers<BackendChatSession>();
    jest.mocked(fetchSettledChatSession).mockReturnValue(page.promise);
    jest
      .spyOn(global, "fetch")
      .mockImplementation(() => new Promise<Response>(() => {}));
    jest.mocked(resumeStream).mockImplementation(async function* () {
      yield continued;
      yield { stream_id: 996, next_cursor: 1, replay_complete: true };
      await new Promise<never>(() => {});
    });

    const refresh = refreshChatSession("session", errorMessage);
    followChatStream("session", stream(996, [82]), errorMessage);
    await waitFor(() =>
      expect(
        useChatSessionStore
          .getState()
          .sessions.get("session")!
          .messageTree.get(2)?.packets
      ).toEqual([continued])
    );
    // The idle snapshot still shows the answer waiting.
    jest.mocked(processRawChatHistory).mockReturnValue(new Map([[2, answer]]));
    page.resolve(savedSession([], null));
    await refresh;

    const session = useChatSessionStore.getState().sessions.get("session")!;
    expect(session.chatState).toBe("streaming");
    expect(session.messageTree.get(2)?.packets).toEqual([continued]);
  });

  test("an answer that a newer stream took over stays with it after that stream ends", () => {
    expect(claimStreamReader(stream(992, [79]))).toBe(true);
    expect(claimStreamReader(stream(993, [79]))).toBe(true);
    releaseStreamReader(stream(993, [79]));

    expect(writesAnswer(992, 79)).toBe(false);
    expect(writesAnswer(993, 79)).toBe(true);
    releaseStreamReader(stream(992, [79]));
  });

  test("incognito closes a lost answer that the server did not park", async () => {
    const lost: Message = {
      ...message(2, "assistant", "Partial"),
      messageId: 76,
      parentNodeId: 1,
      packets: [
        {
          placement: { turn_index: 0, tab_index: 0 },
          obj: { type: "message_delta", content: "Partial" },
        },
      ],
    };
    useChatSessionStore.getState().updateSessionData("session", {
      chatState: "unconfirmed",
      incognito: true,
      messageTree: new Map<number, Message>([
        [
          1,
          {
            ...message(1, "user", "Private question"),
            childrenNodeIds: [2],
            latestChildNodeId: 2,
          },
        ],
        [2, lost],
      ]),
    });
    // A usage-only chat saves only usage rows.
    jest
      .mocked(processRawChatHistory)
      .mockReturnValue(
        new Map([[9, { ...message(9, "assistant", ""), messageId: 76 }]])
      );

    await settle("recovery");

    const answer = useChatSessionStore
      .getState()
      .sessions.get("session")!
      .messageTree.get(2)!;
    expect(answer.message).toBe("Partial");
    expect(answer.packets.at(-1)?.obj.type).toBe("stop");
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
      replay: { streamId: 2, cursor: 7 },
      packets: [
        {
          placement: { turn_index: 0 },
          obj: { type: "message_delta", content: "Live" },
        },
        {
          placement: { turn_index: 1 },
          obj: {
            type: "user_message",
            id: "send",
            message: "Focus here",
            mentions: [],
          },
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
        return Response.json(savedSession(raw, stream(2)));
      // Leave replay pending; this test covers the tree written before it.
      return new Promise<Response>(() => {});
    });
    await refreshChatSession("session", "Check again");
    const refreshed = useChatSessionStore
      .getState()
      .sessions.get("session")
      ?.messageTree.get(2);
    expect(refreshed?.packets).toBe(live.packets);
    expect(refreshed?.replay).toEqual({ streamId: 2, cursor: 7 });
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
    // The stream ID is not a message ID; the answers come from its rows.
    const session = savedSession(raw, stream(901, [2, 3]));
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
        agent_name: null,
      },
    });
    const stop: Packet = {
      placement: { turn_index: 2 },
      obj: { type: "stop" },
    };
    jest.mocked(resumeStream).mockImplementation(async function* () {
      yield approvalRequest(1);
      yield approvalRequest(0);
      yield { stream_id: 901, next_cursor: 2, replay_complete: true };
      yield stop;
      yield { stream_id: 901, next_cursor: 3, replay_complete: true };
    });

    await refreshChatSession("session", errorMessage);

    const tree = () =>
      useChatSessionStore.getState().sessions.get("session")!.messageTree;
    await waitFor(() =>
      expect(tree().get(3)?.replay).toEqual({ streamId: 901, cursor: 3 })
    );
    expect(tree().get(2)?.replay).toEqual({ streamId: 901, cursor: 3 });
    expect(resumeStream).toHaveBeenCalledWith(
      "session",
      901,
      0,
      expect.anything()
    );
    expect(tree().get(2)?.packets).toEqual([approvalRequest(0), stop]);
    expect(tree().get(3)?.packets).toEqual([approvalRequest(1), stop]);
    expect(tree().get(3)?.restoredPacketCount).toBe(1);
  });

  test("a lost resume stream reattaches from its saved cursor while the same stream runs", async () => {
    const log = jest.spyOn(console, "error").mockImplementation(() => {});
    const raw = [
      { ...savedMessage(21, "user", "Question"), latest_child_message: 22 },
      savedMessage(22, "assistant", ""),
    ];
    const tree = processRawChatHistory(raw, [[]]);
    useChatSessionStore.getState().updateSessionData("session", {
      chatState: "streaming",
      messageTree: tree,
    });
    const statuses = [{ is_processing: true, current_stream: stream(22) }];
    jest.spyOn(global, "fetch").mockImplementation(async (input) => {
      const status = statuses.shift();
      if (String(input).endsWith("/status") && status)
        return Response.json(status);
      // Leave later checks pending; this test covers the reattached stream.
      return new Promise<Response>(() => {});
    });
    const delta = (content: string): Packet => ({
      placement: { turn_index: 0 },
      obj: { type: "message_delta", content },
    });
    jest
      .mocked(resumeStream)
      .mockImplementationOnce(async function* () {
        yield delta("Saved");
        yield { stream_id: 22, next_cursor: 1, replay_complete: true };
        yield delta("Not acknowledged");
        throw new TypeError("network error");
      })
      .mockImplementationOnce(async function* () {
        yield delta("Not acknowledged");
        yield approvalRequest("approval");
        yield { stream_id: 22, next_cursor: 3, replay_complete: true };
        // The run waits for the decision.
        await new Promise<never>(() => {});
      });
    const controller = useChatSessionStore
      .getState()
      .sessions.get("session")!.abortController;

    await followChatSession({
      sessionId: "session",
      controller,
      errorMessage,
      stream: stream(22),
      messageMap: tree,
    });

    const answer = () =>
      useChatSessionStore
        .getState()
        .sessions.get("session")!
        .messageTree.get(22);
    await waitFor(() => expect(answer()?.replay?.cursor).toBe(3));
    log.mockRestore();
    expect(resumeStream).toHaveBeenCalledTimes(2);
    expect(resumeStream).toHaveBeenLastCalledWith(
      "session",
      22,
      1,
      expect.anything()
    );
    expect(answer()?.packets).toEqual([
      delta("Saved"),
      delta("Not acknowledged"),
      approvalRequest("approval"),
    ]);
    expect(waitingApprovalIds()).toEqual(["approval"]);
  });

  test("a lost send stream replays its running response into a reset row", async () => {
    const raw = [
      { ...savedMessage(41, "user", "Question"), latest_child_message: 42 },
      savedMessage(42, "assistant", ""),
    ];
    const tree = processRawChatHistory(raw, [[]]);
    const partial: Packet = {
      placement: { turn_index: 0 },
      obj: { type: "message_delta", content: "Partial" },
    };
    tree.set(42, {
      ...tree.get(42)!,
      type: "error",
      errorMessage: "network error",
      streamLost: true,
      packets: [
        partial,
        { placement: { turn_index: 0, tab_index: 0 }, obj: { type: "stop" } },
      ],
    });
    const store = useChatSessionStore.getState();
    const controller = store.sessions.get("session")!.abortController;
    store.updateSessionData("session", {
      chatState: "streaming",
      messageTree: tree,
      sendAcknowledged: Promise.resolve(stream(42)),
      readerFinished: Promise.resolve(),
    });
    const statuses = [{ is_processing: true, current_stream: stream(42) }];
    jest.spyOn(global, "fetch").mockImplementation(async (input) => {
      const status = statuses.shift();
      if (String(input).endsWith("/status") && status)
        return Response.json(status);
      return new Promise<Response>(() => {});
    });
    jest.mocked(resumeStream).mockImplementation(async function* () {
      yield partial;
      yield approvalRequest("approval");
      yield { stream_id: 42, next_cursor: 2, replay_complete: true };
      await new Promise<never>(() => {});
    });

    await settleChatSession({ sessionId: "session", controller, errorMessage });

    const answer = () =>
      useChatSessionStore
        .getState()
        .sessions.get("session")!
        .messageTree.get(42);
    await waitFor(() => expect(answer()?.replay?.cursor).toBe(2));
    expect(resumeStream).toHaveBeenCalledWith(
      "session",
      42,
      0,
      expect.anything()
    );
    expect(answer()).toMatchObject({
      type: "assistant",
      errorMessage: undefined,
      streamLost: undefined,
      packets: [partial, approvalRequest("approval")],
    });
    expect(waitingApprovalIds()).toEqual(["approval"]);
  });

  describe("a continuation the server names", () => {
    const awaitingStop: Packet = {
      placement: { turn_index: 0 },
      obj: { type: "stop", stop_reason: StopReason.AWAITING_APPROVAL },
    };
    const resolved: Packet = {
      placement: { turn_index: 1, tab_index: 0 },
      obj: {
        type: "tool_approval_resolved",
        approval_id: "approval",
        outcome: "approved",
      },
    };

    test("replays its new stream from cursor 0 into the rows it names", async () => {
      const raw = [
        { ...savedMessage(81, "user", "Question"), latest_child_message: 82 },
        savedMessage(82, "assistant", ""),
      ];
      const tree = processRawChatHistory(raw, [[]]);
      // The cursor of the stream that stopped never applies to another stream.
      tree.set(82, {
        ...tree.get(82)!,
        replay: { streamId: 82, cursor: 9 },
        packets: [approvalRequest("approval"), awaitingStop],
      });
      useChatSessionStore.getState().updateSessionData("session", {
        chatState: "input",
        messageTree: tree,
      });
      const fetchMock = jest
        .spyOn(global, "fetch")
        // Leave later checks pending; this test covers the continuation.
        .mockImplementation(() => new Promise<Response>(() => {}));
      const answerText: Packet = {
        placement: { turn_index: 2 },
        obj: { type: "message_delta", content: "Created the issue." },
      };
      jest.mocked(resumeStream).mockImplementation(async function* () {
        yield approvalRequest("approval");
        yield resolved;
        yield { stream_id: 900, next_cursor: 2, replay_complete: true };
        yield answerText;
        yield { stream_id: 900, next_cursor: 3, replay_complete: true };
        await new Promise<never>(() => {});
      });

      // A continuation stream ID is not a message ID.
      followChatStream("session", stream(900, [82]), errorMessage);

      const session = () =>
        useChatSessionStore.getState().sessions.get("session")!;
      expect(session().chatState).toBe("streaming");
      await waitFor(() =>
        expect(session().messageTree.get(82)?.replay).toEqual({
          streamId: 900,
          cursor: 3,
        })
      );
      expect(fetchMock).not.toHaveBeenCalled();
      expect(resumeStream).toHaveBeenCalledWith(
        "session",
        900,
        0,
        expect.anything()
      );
      expect(session().messageTree.get(82)?.packets).toEqual([
        approvalRequest("approval"),
        resolved,
        answerText,
      ]);
    });
  });

  test("an older stream's late batch does not overwrite an answer that its continuation took over", async () => {
    const answer = {
      ...message(2, "assistant", ""),
      messageId: 84,
      parentNodeId: 1,
    };
    useChatSessionStore.getState().updateSessionData("session", {
      chatState: "streaming",
      messageTree: new Map<number, Message>([
        [1, message(1, "user", "Question")],
        [2, answer],
      ]),
    });
    jest
      .spyOn(global, "fetch")
      .mockImplementation(() => new Promise<Response>(() => {}));
    const late = Promise.withResolvers<void>();
    const asked: Packet = approvalRequest("first");
    const stale: Packet = {
      placement: { turn_index: 1 },
      obj: { type: "message_delta", content: "Stale" },
    };
    const continued: Packet = {
      placement: { turn_index: 2 },
      obj: { type: "message_delta", content: "Continued" },
    };
    jest
      .mocked(resumeStream)
      .mockImplementation(async function* (_session, streamId) {
        if (streamId === 980) {
          yield asked;
          yield { stream_id: 980, next_cursor: 1, replay_complete: true };
          await late.promise;
          yield stale;
          yield { stream_id: 980, next_cursor: 2, replay_complete: true };
          await new Promise<never>(() => {});
        }
        yield continued;
        yield { stream_id: 981, next_cursor: 1, replay_complete: true };
        await new Promise<never>(() => {});
      });
    const packets = () =>
      useChatSessionStore.getState().sessions.get("session")!.messageTree.get(2)
        ?.packets;

    followChatStream("session", stream(980, [84]), errorMessage);
    await waitFor(() => expect(packets()).toEqual([asked]));
    followChatStream("session", stream(981, [84]), errorMessage);
    await waitFor(() => expect(packets()).toEqual([continued]));
    late.resolve();
    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(packets()).toEqual([continued]);
  });

  // Readers left open by earlier tests keep their streams, so this test uses
  // its own stream IDs.
  test("a stream that stops for an approval hands its response to the next stream from cursor 0", async () => {
    const raw = [
      { ...savedMessage(91, "user", "Question"), latest_child_message: 92 },
      savedMessage(92, "assistant", ""),
    ];
    const tree = processRawChatHistory(raw, [[]]);
    useChatSessionStore.getState().updateSessionData("session", {
      chatState: "streaming",
      messageTree: tree,
    });
    const continuation = stream(920, [92]);
    jest.spyOn(global, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      // The decision arrived while the response was live, so it named no
      // continuation; the status names the stream that resumes it.
      if (url.endsWith("/status"))
        return Response.json({
          is_processing: true,
          current_stream: continuation,
          has_active_subagents: false,
          has_startable_input: false,
          approvals_version: "2",
          latest_response_id: 92,
        });
      return Response.json(savedSession(raw, continuation));
    });
    const awaitingStop: Packet = {
      placement: { turn_index: 0 },
      obj: { type: "stop", stop_reason: StopReason.AWAITING_APPROVAL },
    };
    const resolved: Packet = {
      placement: { turn_index: 1, tab_index: 0 },
      obj: {
        type: "tool_approval_resolved",
        approval_id: "approval",
        outcome: "approved",
      },
    };
    const replayEnd: Packet = {
      placement: { turn_index: 1 },
      obj: { type: "replay_end" },
    };
    const answerText: Packet = {
      placement: { turn_index: 2 },
      obj: { type: "message_delta", content: "Created the issue." },
    };
    jest
      .mocked(resumeStream)
      .mockImplementation(async function* (_session, streamId) {
        if (streamId === 92) {
          yield approvalRequest("approval");
          yield awaitingStop;
          yield { stream_id: 92, next_cursor: 2, replay_complete: true };
          return;
        }
        yield approvalRequest("approval");
        yield resolved;
        yield replayEnd;
        yield answerText;
        yield { stream_id: 920, next_cursor: 4, replay_complete: true };
        await new Promise<never>(() => {});
      });
    const controller = useChatSessionStore
      .getState()
      .sessions.get("session")!.abortController;

    await followChatSession({
      sessionId: "session",
      controller,
      errorMessage,
      stream: stream(92),
      messageMap: tree,
    });

    const answer = () =>
      useChatSessionStore
        .getState()
        .sessions.get("session")!
        .messageTree.get(92);
    await waitFor(() =>
      expect(answer()?.replay).toEqual({ streamId: 920, cursor: 4 })
    );
    expect(resumeStream).toHaveBeenLastCalledWith(
      "session",
      920,
      0,
      expect.anything()
    );
    // The replay end marks a position and never renders.
    expect(answer()?.packets).toEqual([
      approvalRequest("approval"),
      resolved,
      answerText,
    ]);
  });

  test("a resume stream the server cannot find is not retried", async () => {
    const log = jest.spyOn(console, "error").mockImplementation(() => {});
    const raw = [
      { ...savedMessage(31, "user", "Question"), latest_child_message: 32 },
      savedMessage(32, "assistant", ""),
    ];
    const tree = processRawChatHistory(raw, [[]]);
    useChatSessionStore.getState().updateSessionData("session", {
      chatState: "streaming",
      messageTree: tree,
    });
    // The run ends while the client checks the status after the 404.
    jest.mocked(waitForChatResponseEnd).mockResolvedValue(null);
    jest.spyOn(global, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("resume-stream"))
        return Response.json(
          { detail: "No resumable stream for this chat session" },
          { status: 404 }
        );
      return Response.json(savedSession(raw, null));
    });
    const controller = useChatSessionStore
      .getState()
      .sessions.get("session")!.abortController;

    await followChatSession({
      sessionId: "session",
      controller,
      errorMessage,
      stream: stream(32),
      messageMap: tree,
    });

    const chatState = () =>
      useChatSessionStore.getState().sessions.get("session")!.chatState;
    await waitFor(() => expect(chatState()).toBe("input"));
    log.mockRestore();
    expect(chatState()).toBe("input");
    expect(waitForChatResponseEnd).toHaveBeenCalledWith("session", 32);
    expect(resumeStream).toHaveBeenCalledTimes(1);
  });

  test.each([
    ["a rate limit", 51, () => Response.json({}, { status: 429 })],
    ["a server error", 53, () => Response.json({}, { status: 503 })],
    ["an end before the first cursor", 55, () => new Response("")],
  ])(
    "a resume that fails with %s reattaches while the same stream runs",
    async (_failure, questionId, firstResume) => {
      const log = jest.spyOn(console, "error").mockImplementation(() => {});
      const streamId = questionId + 1;
      const raw = [
        {
          ...savedMessage(questionId, "user", "Question"),
          latest_child_message: streamId,
        },
        savedMessage(streamId, "assistant", ""),
      ];
      const tree = processRawChatHistory(raw, [[]]);
      useChatSessionStore.getState().updateSessionData("session", {
        chatState: "streaming",
        messageTree: tree,
      });
      const resumes = [
        firstResume(),
        new Response(
          new ReadableStream<Uint8Array>({
            start(stream) {
              const lines = [
                approvalRequest("approval"),
                { stream_id: streamId, next_cursor: 1, replay_complete: true },
              ];
              stream.enqueue(
                new TextEncoder().encode(
                  lines.map((line) => JSON.stringify(line) + "\n").join("")
                )
              );
            },
          })
        ),
      ];
      jest.spyOn(global, "fetch").mockImplementation(async (input) => {
        const url = String(input);
        if (url.endsWith("/status"))
          return Response.json({
            is_processing: true,
            current_stream: stream(streamId),
          });
        const resume = url.includes("resume-stream") && resumes.shift();
        return resume || new Promise<Response>(() => {});
      });
      const controller = useChatSessionStore
        .getState()
        .sessions.get("session")!.abortController;

      await followChatSession({
        sessionId: "session",
        controller,
        errorMessage,
        stream: stream(streamId),
        messageMap: tree,
      });

      const answer = () =>
        useChatSessionStore
          .getState()
          .sessions.get("session")!
          .messageTree.get(streamId);
      await waitFor(() => expect(answer()?.replay?.cursor).toBe(1));
      log.mockRestore();
      expect(resumes).toEqual([]);
      expect(waitingApprovalIds()).toEqual(["approval"]);
    }
  );

  test("a resume the server refuses for auth leaves the chat unconfirmed", async () => {
    const log = jest.spyOn(console, "error").mockImplementation(() => {});
    const raw = [
      { ...savedMessage(61, "user", "Question"), latest_child_message: 62 },
      savedMessage(62, "assistant", ""),
    ];
    const tree = processRawChatHistory(raw, [[]]);
    useChatSessionStore.getState().updateSessionData("session", {
      chatState: "streaming",
      messageTree: tree,
    });
    jest
      .spyOn(global, "fetch")
      .mockImplementation(async () => Response.json({}, { status: 401 }));
    const controller = useChatSessionStore
      .getState()
      .sessions.get("session")!.abortController;

    await followChatSession({
      sessionId: "session",
      controller,
      errorMessage,
      stream: stream(62),
      messageMap: tree,
    });

    const session = () =>
      useChatSessionStore.getState().sessions.get("session")!;
    await waitFor(() => expect(session().chatState).toBe("unconfirmed"));
    log.mockRestore();
    expect(session().chatState).toBe("unconfirmed");
    expect(session().uncaughtError).toEqual({ error: errorMessage });
    expect(
      jest.mocked(global.fetch).mock.calls.map(([url]) => String(url))
    ).toEqual([
      expect.stringContaining("resume-stream"),
      expect.stringContaining("/status"),
    ]);
  });

  test("an incognito lost send keeps its received output when replay is unavailable", async () => {
    const log = jest.spyOn(console, "error").mockImplementation(() => {});
    const raw = [
      { ...savedMessage(71, "user", "Question"), latest_child_message: 72 },
      savedMessage(72, "assistant", ""),
    ];
    const tree = processRawChatHistory(raw, [[]]);
    const partial: Packet = {
      placement: { turn_index: 0 },
      obj: { type: "message_delta", content: "Partial" },
    };
    const localStop: Packet = {
      placement: { turn_index: 0, tab_index: 0 },
      obj: { type: "stop" },
    };
    tree.set(72, {
      ...tree.get(72)!,
      type: "error",
      message: "Partial",
      errorMessage: "network error",
      streamLost: true,
      packets: [partial, localStop],
    });
    const store = useChatSessionStore.getState();
    const controller = store.sessions.get("session")!.abortController;
    store.updateSessionData("session", {
      incognito: true,
      chatState: "streaming",
      messageTree: tree,
      sendAcknowledged: Promise.resolve(stream(72)),
      readerFinished: Promise.resolve(),
    });
    const statuses = [
      { is_processing: true, current_stream: stream(72) },
      { is_processing: false, current_stream: null },
    ];
    jest.spyOn(global, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/status")) return Response.json(statuses.shift());
      // The saved answer was not parked.
      if (url.includes("/get-chat-session/"))
        return Response.json(savedSession(raw, null));
      return Response.json(
        { detail: "No resumable stream for this chat session" },
        { status: 404 }
      );
    });

    await settleChatSession({ sessionId: "session", controller, errorMessage });

    const session = () =>
      useChatSessionStore.getState().sessions.get("session")!;
    await waitFor(() => expect(session().chatState).toBe("input"));
    log.mockRestore();
    expect(session().messageTree.get(72)).toMatchObject({
      message: "Partial",
      packets: [partial, localStop],
      streamLost: undefined,
    });
  });

  test("a lost stream keeps its mark only while its run continues", () => {
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
            agent_name: null,
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

    expect(merged("running").get(2)?.streamLost).toBe(true);
    expect(merged("error").get(2)?.streamLost).toBe(false);
  });

  test("a parked answer's saved waiting request replaces a failed local prefix", () => {
    const raw = [
      { ...savedMessage(1, "user", "Question"), latest_child_message: 2 },
      savedMessage(2, "assistant", ""),
    ];
    // The send stream dropped before the request arrived.
    const local = processRawChatHistory(raw, [[]]);
    local.set(2, {
      ...local.get(2)!,
      type: "error",
      errorMessage: "network error",
      streamLost: true,
      packets: [],
    });
    const saved = processRawChatHistory(raw, [[]]);
    saved.set(2, {
      ...saved.get(2)!,
      responseStatus: "suspended",
      packets: [approvalRequest("approval")],
    });

    const merged = preserveFailedMessages(saved, local);

    expect(merged.get(2)).toMatchObject({
      type: "assistant",
      packets: [approvalRequest("approval")],
    });
    expect(readWaitingToolApprovals(merged)).toHaveLength(1);
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
        sendAcknowledged: Promise.resolve(stream(40)),
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

  test("refresh drops loaded history whose waiting card the latest page no longer holds", async () => {
    const history = Array.from({ length: 40 }, (_, index) =>
      savedMessage(
        index + 1,
        index % 2 ? "assistant" : "user",
        `Message ${index + 1}`
      )
    );
    const all = savedSession(history, null);
    all.packets[1] = [
      {
        placement: { turn_index: 0, tab_index: 0 },
        obj: {
          type: "tool_approval_request",
          approval_id: "approval",
          tool_call_id: "call",
          tool_name: "mcp__3__github__create_issue",
          display_name: "Create issue",
          arguments: {},
          agent_name: "researcher",
        },
      },
    ];
    // The request was decided elsewhere: the latest page holds every reply
    // with a waiting card, and this one is not among them.
    const page = {
      ...savedSession(history.slice(20), null),
      has_older_messages: true,
    };
    useChatSessionStore.getState().updateSessionData("session", {
      messageTree: processRawChatHistory(all.messages, all.packets),
      hasOlderMessages: false,
    });
    jest.spyOn(global, "fetch").mockResolvedValue(Response.json(page));
    await refreshChatSession("session", "Check again");
    const session = useChatSessionStore.getState().sessions.get("session")!;
    expect(
      getLatestMessageChain(session.messageTree).map(
        (message) => message.messageId
      )
    ).toEqual(history.slice(20).map((message) => message.message_id));
    expect(readWaitingToolApprovals(session.messageTree)).toEqual([]);
    expect(session.hasOlderMessages).toBe(true);
  });

  // A queued or interrupting turn starts on the server; this browser loads
  // its saved question, then follows the running response.
  test("refresh shows the skills a turn from the queue mentioned", async () => {
    const raw: BackendMessage[] = [
      savedMessage(1, "user", "Question"),
      savedMessage(2, "assistant", "Answer"),
      {
        ...savedMessage(3, "user", "@code-review the diff"),
        mentions: [
          { type: "skill", name: "code-review", version_id: "v-code-review" },
        ],
      },
      savedMessage(4, "assistant", ""),
    ];
    useChatSessionStore.getState().updateSessionData("session", {
      messageTree: processRawChatHistory(raw.slice(0, 2), [[]]),
    });
    jest.spyOn(global, "fetch").mockImplementation(async (input) => {
      if (String(input).includes("get-chat-session"))
        return Response.json(savedSession(raw, stream(4)));
      // Leave replay pending; this test covers the tree written before it.
      return new Promise<Response>(() => {});
    });
    await refreshChatSession("session", "Check again");
    const question = useChatSessionStore
      .getState()
      .sessions.get("session")
      ?.messageTree.get(3);
    expect(question?.mentions).toEqual([
      { type: "skill", name: "code-review", version_id: "v-code-review" },
    ]);
  });

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
              stream(2)
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
