import { act, renderHook, waitFor } from "@testing-library/react";
import { ReadonlyURLSearchParams } from "next/navigation";
import useChatController from "@/hooks/useChatController";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import {
  createChatSession,
  endIncognitoSession,
  processRawChatHistory,
  resumeStream,
  sendMessage,
  setPreferredResponse,
  ApprovalPendingError,
  ChatSendRejectedError,
  type PacketType,
} from "@/app/app/services/lib";
import { endedRunStatus, isWorking } from "@/lib/chat/runStatus";
import { getLatestMessageChain } from "@/app/app/services/messageTree";
import { toast } from "@opal/layouts";
import {
  readWaitingToolRequests,
  useToolRequestUi,
} from "@/lib/chat/toolApprovals";
import {
  claimStreamReader,
  followChatStream,
  refreshChatSession,
} from "@/lib/chat/settleChatSession";
import type { MinimalAgent } from "@/lib/agents/types";
import type { LlmManager } from "@/lib/hooks";
import {
  fetchSettledChatSession,
  waitForChatResponseEnd,
} from "@/lib/chat/sessionReadiness";
import type { ToolConfigurationHandle } from "@/lib/tools/hooks";
import { ChatFileType, type Message } from "@/app/app/types";
import { type ProjectFile, UserFileStatus } from "@/lib/projects/types";
import { fileDescriptorToProjectFile } from "@/lib/projects/utils";
import { useAppPosition } from "@/lib/navigation/hooks";
import { StopReason } from "@/app/app/services/streamingModels";

jest.mock("next/navigation", () => {
  const actual = jest.requireActual("next/navigation");
  const params = new actual.ReadonlyURLSearchParams();
  const router = { replace: jest.fn(), push: jest.fn() };
  return {
    ...actual,
    useSearchParams: () => params,
    usePathname: () => "/app",
    useRouter: () => router,
  };
});
jest.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));
jest.mock("@opal/layouts", () => ({
  toast: { error: jest.fn(), warning: jest.fn() },
}));
jest.mock("@/lib/languageModels/utils", () => ({
  structureValue: () => "model",
}));
jest.mock("@/lib/connectors/hooks", () => ({
  useAvailableSources: () => ({ availableSources: [], settled: true }),
}));
jest.mock("@/hooks/useChatSessions", () => ({
  __esModule: true,
  default: () => ({
    refreshChatSessions: jest.fn(),
    addPendingChatSession: jest.fn(),
  }),
}));
jest.mock("@/lib/agents/hooks", () => ({
  usePinnedAgents: () => ({
    pinnedAgents: [],
    togglePinnedAgent: jest.fn(async () => {}),
  }),
}));
jest.mock("@/lib/projects/providers", () => ({
  useProjectsContext: () => ({
    fetchProjects: jest.fn(),
    setCurrentMessageFiles: jest.fn(),
    beginUpload: jest.fn(),
  }),
}));
const mockIncognitoEnabledRef = { current: false };
const mockIncognitoSessionIdRef: { current: string | null } = { current: null };
jest.mock("@/providers/IncognitoProvider", () => ({
  useIncognito: () => ({
    incognitoEnabledRef: mockIncognitoEnabledRef,
    incognitoSessionId: mockIncognitoSessionIdRef.current,
    incognitoSessionIdRef: mockIncognitoSessionIdRef,
  }),
}));
jest.mock("@/app/app/services/lib", () => {
  class ChatSendRejectedError extends Error {}
  return {
    updateLlmOverrideForChatSession: jest.fn(),
    processRawChatHistory: jest.fn(() => new Map()),
    sendMessage: jest.fn(),
    resumeStream: jest.fn(),
    setPreferredResponse: jest.fn(),
    createChatSession: jest.fn(),
    endIncognitoSession: jest.fn(async () => true),
    buildChatUrl: () => "/app?chatId=session",
    ChatSendRejectedError,
    ApprovalPendingError: class extends ChatSendRejectedError {},
  };
});
jest.mock("@/lib/chat/settleChatSession", () => ({
  ...jest.requireActual("@/lib/chat/settleChatSession"),
  refreshChatSession: jest.fn(async () => {}),
}));
jest.mock("@/lib/chat/sessionReadiness", () => ({
  CHAT_STATUS_POLL_MS: 0,
  readChatSessionStatus: jest.fn(async () => ({
    is_processing: false,
    current_stream: null,
    has_startable_input: false,
    approvals_version: "0",
    has_active_subagents: false,
    latest_response_id: null,
  })),
  waitForChatResponseEnd: jest.fn(async () => null),
  fetchSettledChatSession: jest.fn(async () => ({
    messages: [],
    packets: [],
    is_processing: false,
    current_stream: null,
  })),
}));

const toolConfiguration: ToolConfigurationHandle = {
  stateOf: jest.fn(),
  setToolState: jest.fn(),
  toggleToolState: jest.fn(),
  clearPreferredTool: jest.fn(),
  preferredToolId: null,
  preferredAction: null,
  disabledToolIds: [],
  isIntegrationEnabled: jest.fn(() => true),
  setIntegrationEnabled: jest.fn(),
  allowed: null,
  ready: true,
  optionsLoaded: true,
  filters: {
    selectedSources: null,
    documentSets: [],
    tags: [],
    timeRange: null,
  },
  setFilters: jest.fn(),
  handOffTo: jest.fn(),
  handOffToNewChatWith: jest.fn(),
};

const originalFetch = global.fetch;
afterEach(() => {
  mockIncognitoEnabledRef.current = false;
  mockIncognitoSessionIdRef.current = null;
  global.fetch = originalFetch;
  jest.restoreAllMocks();
  jest.clearAllMocks();
});

function createLlmManager(): LlmManager {
  return {
    currentLlm: { name: "provider", provider: "openai", modelName: "model" },
    updateCurrentLlm: jest.fn(),
    temperature: 0,
    updateTemperature: jest.fn(),
    temperatureExplicitlySet: false,
    reasoningEffort: null,
    updateReasoningEffort: jest.fn(),
    hasBoundSession: true,
    persistOverrides: jest.fn(async () => {}),
    updateModelOverrideBasedOnChatSession: jest.fn(),
    imageFilesPresent: false,
    updateImageFilesPresent: jest.fn(),
    activeAgent: null,
    maxTemperature: 2,
    hasTemperatureOverride: false,
    llmProviders: [],
    modelPaging: {
      hasMore: false,
      isLoading: false,
      loadMore: jest.fn(async () => false),
      search: jest.fn(async () => false),
      searchHasMore: false,
      loadMoreSearch: jest.fn(async () => {}),
    },
    isLoadingProviders: false,
    hasAnyProvider: false,
  };
}

test.each([false, true])(
  "a failed private send restores its draft only if the composer stays private (switched: %s)",
  async (switched) => {
    const previousUrl = window.location.href;
    window.history.replaceState(null, "", "/app");
    jest.spyOn(console, "error").mockImplementation(() => {});
    useChatSessionStore.setState({
      sessions: new Map(),
      currentSessionId: null,
    });
    mockIncognitoEnabledRef.current = true;
    const creation = Promise.withResolvers<string>();
    jest.mocked(createChatSession).mockReturnValueOnce(creation.promise);
    const restoreInputBar = jest.fn();
    const { result } = renderHook(() =>
      useChatController({
        llmManager: createLlmManager(),
        toolConfiguration,
        activeAgent: undefined,
        availableAgents: [],
        existingChatSessionId: null,
        selectedDocuments: [],
        searchParams: new ReadonlyURLSearchParams(),
        resetInputBar: jest.fn(),
        restoreInputBar,
      })
    );
    try {
      await act(async () => {
        const send = result.current.onSubmit({
          message: "private text",
          mentions: [],
          currentMessageFiles: [],
          deepResearch: false,
        });
        mockIncognitoEnabledRef.current = !switched;
        creation.reject(new Error("Session creation failed"));
        await send;
      });

      expect(restoreInputBar).toHaveBeenCalledTimes(switched ? 0 : 1);
      if (!switched) {
        expect(restoreInputBar).toHaveBeenCalledWith({
          message: "private text",
          mentions: [],
          files: [],
        });
      }
    } finally {
      window.history.replaceState(null, "", previousUrl);
    }
  }
);

test.each([false, true])(
  "New Session handles a pending first send (private: %s)",
  async (incognito) => {
    mockIncognitoEnabledRef.current = incognito;
    useChatSessionStore.setState({
      sessions: new Map(),
      currentSessionId: null,
    });
    const creation = Promise.withResolvers<string>();
    jest.mocked(createChatSession).mockReturnValueOnce(creation.promise);
    if (!incognito) {
      jest.mocked(sendMessage).mockImplementationOnce(async function* () {
        yield sentTurn;
        yield { placement: { turn_index: 0 }, obj: { type: "stop" } };
      });
    }
    const resetInputBar = jest.fn();
    const { result } = renderHook(() => ({
      position: useAppPosition(),
      controller: useChatController({
        llmManager: createLlmManager(),
        toolConfiguration,
        activeAgent: undefined,
        availableAgents: [],
        existingChatSessionId: null,
        selectedDocuments: [],
        searchParams: new ReadonlyURLSearchParams(),
        resetInputBar,
        restoreInputBar: jest.fn(),
      }),
    }));

    await act(async () => {
      const send = result.current.controller.onSubmit({
        message: "Send before opening a fresh session",
        mentions: [],
        currentMessageFiles: [],
        deepResearch: false,
      });
      result.current.position.openNewSession();
      creation.resolve("session");
      await send;
    });

    if (incognito) {
      expect(endIncognitoSession).toHaveBeenCalledWith("session");
      expect(sendMessage).not.toHaveBeenCalled();
    } else {
      expect(endIncognitoSession).not.toHaveBeenCalled();
      expect(sendMessage).toHaveBeenCalled();
    }
    expect(useChatSessionStore.getState().currentSessionId).toBeNull();
    expect(resetInputBar).not.toHaveBeenCalled();
  }
);

test("a private chat created for a replaced private session never opens", async () => {
  mockIncognitoEnabledRef.current = true;
  mockIncognitoSessionIdRef.current = "private-a";
  useChatSessionStore.setState({ sessions: new Map(), currentSessionId: null });
  const creation = Promise.withResolvers<string>();
  jest.mocked(createChatSession).mockReturnValueOnce(creation.promise);
  const { result } = renderHook(() =>
    useChatController({
      llmManager: createLlmManager(),
      toolConfiguration,
      activeAgent: undefined,
      availableAgents: [],
      existingChatSessionId: null,
      selectedDocuments: [],
      searchParams: new ReadonlyURLSearchParams(),
      resetInputBar: jest.fn(),
      restoreInputBar: jest.fn(),
    })
  );

  await act(async () => {
    const send = result.current.onSubmit({
      message: "private text",
      mentions: [],
      currentMessageFiles: [],
      deepResearch: false,
    });
    // A back/forward restore, or Exit and a new private session, mints a new
    // private session while private mode stays on.
    mockIncognitoSessionIdRef.current = "private-b";
    creation.resolve("session");
    await send;
  });

  expect(endIncognitoSession).toHaveBeenCalledWith("session");
  expect(sendMessage).not.toHaveBeenCalled();
  expect(useChatSessionStore.getState().currentSessionId).toBeNull();
});

test.each([
  { isNewSession: false, stop: true },
  { isNewSession: true, stop: true },
  { isNewSession: false, stop: false },
])(
  "abort during preparation preserves drafts only for Stop ($isNewSession, $stop)",
  async ({ isNewSession, stop }) => {
    const preferences = Promise.withResolvers<void>();
    const llmManager = createLlmManager();
    llmManager.persistOverrides = jest.fn(() => preferences.promise);
    global.fetch = jest.fn(async () => new Response(null, { status: 200 }));
    useChatSessionStore.setState({
      sessions: new Map(),
      currentSessionId: isNewSession ? null : "session",
    });
    if (!isNewSession) useChatSessionStore.getState().createSession("session");
    jest.mocked(createChatSession).mockResolvedValue("session");
    const restoreInputBar = jest.fn();
    const { result, unmount } = renderHook(() =>
      useChatController({
        llmManager,
        toolConfiguration,
        activeAgent: undefined,
        availableAgents: [],
        existingChatSessionId: isNewSession ? null : "session",
        selectedDocuments: [],
        searchParams: new ReadonlyURLSearchParams(),
        resetInputBar: jest.fn(),
        restoreInputBar,
      })
    );

    let pendingSend: Promise<void> | undefined;
    act(() => {
      pendingSend = result.current.onSubmit({
        message: "Do not send this after Stop @code-review",
        mentions: [{ type: "skill", name: "code-review" }],
        currentMessageFiles: [],
        deepResearch: false,
      });
    });
    await waitFor(() =>
      expect(llmManager.persistOverrides).toHaveBeenCalledWith("session")
    );
    expect(
      useChatSessionStore.getState().sessions.get("")?.abortController
    ).not.toBe(
      useChatSessionStore.getState().sessions.get("session")?.abortController
    );
    expect(
      useChatSessionStore.getState().sessions.get("session")?.chatState
    ).toBe("loading");
    if (stop) {
      await act(async () => result.current.stopGenerating());
      expect(restoreInputBar).toHaveBeenCalledWith({
        message: "Do not send this after Stop @code-review",
        mentions: [{ type: "skill", name: "code-review" }],
        files: [],
      });
    } else {
      useChatSessionStore
        .getState()
        .sessions.get("session")!
        .abortController.abort();
      unmount();
      expect(restoreInputBar).not.toHaveBeenCalled();
    }
    expect(global.fetch).not.toHaveBeenCalled();
    expect(
      useChatSessionStore.getState().sessions.get("session")?.chatState
    ).toBe(stop ? "input" : "loading");

    await act(async () => {
      preferences.resolve();
      await pendingSend;
    });
    expect(sendMessage).not.toHaveBeenCalled();
    expect(restoreInputBar).toHaveBeenCalledTimes(stop ? 1 : 0);
    if (stop) {
      expect(
        useChatSessionStore.getState().sessions.get("session")?.messageTree.size
      ).toBe(0);
    }
  }
);

test("Stop drains multi-model packets and finishes every panel before releasing incognito input", async () => {
  const tail = Promise.withResolvers<void>();
  jest.spyOn(Promise, "withResolvers").mockImplementation(() => {
    throw new Error("Promise.withResolvers is unavailable");
  });
  const llmManager = createLlmManager();
  global.fetch = jest.fn(async () => new Response(null, { status: 200 }));
  useChatSessionStore.setState({
    sessions: new Map(),
    currentSessionId: "session",
  });
  useChatSessionStore.getState().createSession("session", { incognito: true });
  jest.mocked(sendMessage).mockImplementation(async function* () {
    yield {
      user_message_id: 11,
      responses: [
        { message_id: 12, model_name: "First" },
        { message_id: 13, model_name: "Second" },
      ],
    };
    await tail.promise;
    for (const model_index of [0, 1]) {
      yield {
        placement: { turn_index: 0, tab_index: 0, model_index },
        obj: { type: "message_delta", content: `Final output ${model_index}` },
      };
      yield {
        placement: { turn_index: 0, tab_index: 0, model_index },
        obj: { type: "stop" },
      };
    }
  });
  const { result } = renderHook(() =>
    useChatController({
      llmManager,
      toolConfiguration,
      activeAgent: undefined,
      availableAgents: [],
      existingChatSessionId: "session",
      selectedDocuments: [],
      searchParams: new ReadonlyURLSearchParams(),
      resetInputBar: jest.fn(),
      restoreInputBar: jest.fn(),
    })
  );
  let sending: Promise<void> | undefined;
  act(() => {
    sending = result.current.onSubmit({
      message: "Compare answers",
      mentions: [],
      currentMessageFiles: [],
      deepResearch: false,
      selectedModels: ["First", "Second"].map((name) => ({
        name: "provider",
        provider: "openai",
        modelName: name,
        modelConfigurationId: null,
        displayName: name,
      })),
    });
  });
  await waitFor(() => expect(sendMessage).toHaveBeenCalled());
  let stopping: Promise<void> | undefined;
  act(() => {
    stopping = result.current.stopGenerating();
  });
  await waitFor(() =>
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/chat/stop-chat-session/session",
      expect.objectContaining({ method: "POST" })
    )
  );
  expect(waitForChatResponseEnd).not.toHaveBeenCalled();
  expect(
    useChatSessionStore.getState().sessions.get("session")?.chatState
  ).toBe("cancelling");
  await act(async () => {
    tail.resolve();
    await Promise.all([sending, stopping]);
  });
  const session = useChatSessionStore.getState().sessions.get("session");
  expect(session?.chatState).toBe("input");
  const assistants = [...session!.messageTree.values()].filter(
    (message) => message.type === "assistant"
  );
  expect(assistants).toHaveLength(2);
  for (const [index, assistant] of assistants.entries()) {
    expect(assistant.is_generating).toBe(false);
    expect(assistant.packets).toEqual([
      expect.objectContaining({
        obj: { type: "message_delta", content: `Final output ${index}` },
      }),
      expect.objectContaining({ obj: { type: "stop" } }),
    ]);
  }
});

test.each([false, true])(
  "provider failure preserves streamed content (multi-model: %s)",
  async (multiModel) => {
    jest.spyOn(console, "log").mockImplementation(() => {});
    useChatSessionStore.setState({
      sessions: new Map(),
      currentSessionId: "session",
    });
    useChatSessionStore
      .getState()
      .createSession("session", { incognito: true });
    jest.mocked(sendMessage).mockImplementation(async function* () {
      if (multiModel) {
        yield {
          user_message_id: 11,
          responses: [
            { message_id: 12, model_name: "First" },
            { message_id: 13, model_name: "Second" },
          ],
        };
      } else {
        yield { user_message_id: 11, reserved_assistant_message_id: 12 };
      }
      yield {
        placement: { turn_index: 0, model_index: multiModel ? 0 : undefined },
        obj: { type: "message_delta", content: "Partial answer" },
      };
      yield {
        error: "Provider failed",
        error_code: "API_ERROR",
        is_retryable: true,
        stack_trace: "",
        details: multiModel ? { model_index: 0 } : {},
      };
      if (multiModel)
        yield { placement: { turn_index: 0 }, obj: { type: "stop" } };
    });
    const { result } = renderHook(() =>
      useChatController({
        llmManager: createLlmManager(),
        toolConfiguration,
        activeAgent: undefined,
        availableAgents: [],
        existingChatSessionId: "session",
        selectedDocuments: [],
        searchParams: new ReadonlyURLSearchParams(),
        resetInputBar: jest.fn(),
        restoreInputBar: jest.fn(),
      })
    );
    await act(async () =>
      result.current.onSubmit({
        message: "Question",
        mentions: [],
        currentMessageFiles: [],
        deepResearch: false,
        selectedModels: multiModel
          ? ["First", "Second"].map((name) => ({
              name: "provider",
              provider: "openai",
              modelName: name,
              displayName: name,
              modelConfigurationId: null,
            }))
          : undefined,
      })
    );
    const error = [
      ...useChatSessionStore
        .getState()
        .sessions.get("session")!
        .messageTree.values(),
    ].find((message) => message.type === "error");
    expect(error).toMatchObject({
      errorMessage: "Provider failed",
      errorCode: "API_ERROR",
      isRetryable: true,
    });
    expect(error?.message).not.toBe("Provider failed");
    expect(
      error?.packets.some(
        (packet) =>
          packet.obj.type === "message_delta" &&
          packet.obj.content === "Partial answer"
      )
    ).toBe(true);
    expect(error?.packets.at(-1)?.obj.type).toBe("stop");
  }
);

test("a lost stream keeps its waiting approval open after the server is idle", async () => {
  jest.spyOn(console, "log").mockImplementation(() => {});
  useToolRequestUi.setState({
    localStatuses: new Map(),
    localAnswers: new Map(),
    nudge: null,
  });
  const idle = Promise.withResolvers<null>();
  jest.mocked(waitForChatResponseEnd).mockReturnValueOnce(idle.promise);
  useChatSessionStore.setState({
    sessions: new Map(),
    currentSessionId: "session",
  });
  useChatSessionStore.getState().createSession("session", { incognito: true });
  jest.mocked(sendMessage).mockImplementation(async function* () {
    yield { user_message_id: 11, reserved_assistant_message_id: 12 };
    yield {
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
    };
    throw new Error("network error");
  });
  const { result } = renderHook(() =>
    useChatController({
      llmManager: createLlmManager(),
      toolConfiguration,
      activeAgent: undefined,
      availableAgents: [],
      existingChatSessionId: "session",
      selectedDocuments: [],
      searchParams: new ReadonlyURLSearchParams(),
      resetInputBar: jest.fn(),
      restoreInputBar: jest.fn(),
    })
  );
  const tree = () =>
    useChatSessionStore.getState().sessions.get("session")!.messageTree;
  const waitingIds = () =>
    readWaitingToolRequests(tree()).flatMap((item) =>
      item.kind === "approval" ? [item.request.approval_id] : []
    );

  let sending: Promise<void> | undefined;
  act(() => {
    sending = result.current.onSubmit({
      message: "Open an issue",
      mentions: [],
      currentMessageFiles: [],
      deepResearch: false,
    });
  });
  await waitFor(() => expect(waitForChatResponseEnd).toHaveBeenCalled());
  const lost = [...tree().values()].find((message) => message.type === "error");
  expect(lost?.packets.at(-1)?.obj.type).toBe("stop");
  expect(waitingIds()).toEqual(["approval"]);

  await act(async () => {
    idle.resolve(null);
    await sending;
  });
  // An idle server can still wait for the decision.
  expect(waitingIds()).toEqual(["approval"]);
});

test("a continuation that names the send's own stream keeps the send as its only reader", async () => {
  jest.spyOn(console, "log").mockImplementation(() => {});
  useToolRequestUi.setState({
    localStatuses: new Map(),
    localAnswers: new Map(),
    nudge: null,
  });
  useChatSessionStore.setState({
    sessions: new Map(),
    currentSessionId: "session",
  });
  useChatSessionStore.getState().createSession("session");
  const answerEnds = Promise.withResolvers<void>();
  jest.mocked(sendMessage).mockImplementation(async function* () {
    yield { user_message_id: 11, reserved_assistant_message_id: 12 };
    yield {
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
    };
    await answerEnds.promise;
  });
  const { result } = renderHook(() =>
    useChatController({
      llmManager: createLlmManager(),
      toolConfiguration,
      activeAgent: undefined,
      availableAgents: [],
      existingChatSessionId: "session",
      selectedDocuments: [],
      searchParams: new ReadonlyURLSearchParams(),
      resetInputBar: jest.fn(),
      restoreInputBar: jest.fn(),
    })
  );
  const tree = () =>
    useChatSessionStore.getState().sessions.get("session")!.messageTree;
  const waitingIds = () =>
    readWaitingToolRequests(tree()).flatMap((item) =>
      item.kind === "approval" ? [item.request.approval_id] : []
    );

  let sending: Promise<void> | undefined;
  act(() => {
    sending = result.current.onSubmit({
      message: "Open an issue",
      mentions: [],
      currentMessageFiles: [],
      deepResearch: false,
    });
  });
  await waitFor(() => expect(waitingIds()).toEqual(["approval"]));

  act(() =>
    followChatStream("session", { stream_id: 12, response_ids: [12] }, "Check")
  );

  expect(resumeStream).not.toHaveBeenCalled();
  // The answer keeps the output its send reader received.
  expect(waitingIds()).toEqual(["approval"]);
  await act(async () => {
    answerEnds.resolve();
    await sending;
  });
});

test("a send reader's later flush keeps an answer that its continuation took over", async () => {
  jest.spyOn(console, "log").mockImplementation(() => {});
  useToolRequestUi.setState({
    localStatuses: new Map(),
    localAnswers: new Map(),
    nudge: null,
  });
  useChatSessionStore.setState({
    sessions: new Map(),
    currentSessionId: "session",
  });
  useChatSessionStore.getState().createSession("session");
  const takenOver = Promise.withResolvers<void>();
  const answerEnds = Promise.withResolvers<void>();
  jest.mocked(sendMessage).mockImplementation(async function* () {
    yield { user_message_id: 31, reserved_assistant_message_id: 32 };
    yield {
      placement: { turn_index: 1, tab_index: 0 },
      obj: { type: "message_delta", content: "Before" },
    };
    await takenOver.promise;
    yield {
      placement: { turn_index: 1, tab_index: 0 },
      obj: { type: "message_delta", content: " stale" },
    };
    await answerEnds.promise;
  });
  const { result } = renderHook(() =>
    useChatController({
      llmManager: createLlmManager(),
      toolConfiguration,
      activeAgent: undefined,
      availableAgents: [],
      existingChatSessionId: "session",
      selectedDocuments: [],
      searchParams: new ReadonlyURLSearchParams(),
      resetInputBar: jest.fn(),
      restoreInputBar: jest.fn(),
    })
  );
  const answer = () =>
    [
      ...useChatSessionStore
        .getState()
        .sessions.get("session")!
        .messageTree.values(),
    ].find((message) => message.messageId === 32);

  let sending: Promise<void> | undefined;
  act(() => {
    sending = result.current.onSubmit({
      message: "Open an issue",
      mentions: [],
      currentMessageFiles: [],
      deepResearch: false,
    });
  });
  await waitFor(() => expect(answer()?.packets).toHaveLength(1));

  // A continuation of the answer claims it and writes its rows.
  const continuedPacket = {
    placement: { turn_index: 2, tab_index: 0 },
    obj: { type: "message_delta" as const, content: "Continued" },
  };
  const continued = { ...answer()!, packets: [continuedPacket] };
  act(() => {
    expect(claimStreamReader({ stream_id: 940, response_ids: [32] })).toBe(
      true
    );
    const store = useChatSessionStore.getState();
    store.updateSessionMessageTree(
      "session",
      new Map(store.sessions.get("session")!.messageTree).set(
        continued.nodeId,
        continued
      )
    );
  });
  await act(async () => {
    takenOver.resolve();
    await new Promise((resolve) => setTimeout(resolve, 50));
  });

  expect(answer()?.packets).toEqual([continuedPacket]);
  await act(async () => {
    answerEnds.resolve();
    await sending;
  });
  expect(answer()?.packets).toEqual([continuedPacket]);
});

test("a send refused for a waiting approval restores the draft and points at the card", async () => {
  useToolRequestUi.setState({
    localStatuses: new Map(),
    localAnswers: new Map(),
    nudge: null,
  });
  useChatSessionStore.setState({
    sessions: new Map(),
    currentSessionId: "session",
  });
  const store = useChatSessionStore.getState();
  store.createSession("session");
  const history = new Map<number, Message>([
    [
      1,
      {
        nodeId: 1,
        messageId: 1,
        type: "user",
        message: "Question",
        files: [],
        packets: [],
        toolCall: null,
        parentNodeId: null,
        latestChildNodeId: 2,
        childrenNodeIds: [2],
      },
    ],
    [
      2,
      {
        nodeId: 2,
        messageId: 2,
        type: "assistant",
        message: "",
        files: [],
        packets: [
          {
            placement: { turn_index: 1, tab_index: 0 },
            obj: {
              type: "tool_approval_request",
              approval_id: "approval-1",
              tool_call_id: "call-1",
              tool_name: "mcp__3__github__create_issue",
              display_name: "Create issue",
              arguments: {},
              agent_name: null,
            },
          },
        ],
        toolCall: null,
        parentNodeId: 1,
      },
    ],
  ]);
  store.updateSessionMessageTree("session", history);
  jest.mocked(sendMessage).mockImplementation(() => {
    throw new ApprovalPendingError("A tool approval waits");
  });
  const restoreInputBar = jest.fn();
  const { result } = renderHook(() =>
    useChatController({
      llmManager: createLlmManager(),
      toolConfiguration,
      activeAgent: undefined,
      availableAgents: [],
      existingChatSessionId: "session",
      selectedDocuments: [],
      searchParams: new ReadonlyURLSearchParams(),
      resetInputBar: jest.fn(),
      restoreInputBar,
    })
  );

  await act(async () =>
    result.current.onSubmit({
      message: "Another question",
      mentions: [],
      currentMessageFiles: [],
      deepResearch: false,
    })
  );

  expect(restoreInputBar).toHaveBeenCalledWith({
    message: "Another question",
    mentions: [],
    files: [],
  });
  expect(toast.warning).toHaveBeenCalledWith("pendingToolApproval.toast");
  expect(toast.error).not.toHaveBeenCalled();
  expect(useToolRequestUi.getState().nudge?.requestId).toBe("approval-1");
  expect(refreshChatSession).not.toHaveBeenCalled();
});

test("a send refused for an approval this chat does not show settles with the saved session", async () => {
  useToolRequestUi.setState({
    localStatuses: new Map(),
    localAnswers: new Map(),
    nudge: null,
  });
  useChatSessionStore.setState({
    sessions: new Map(),
    currentSessionId: "session",
  });
  useChatSessionStore.getState().createSession("session");
  jest.mocked(sendMessage).mockImplementation(() => {
    throw new ApprovalPendingError("A tool approval waits");
  });
  const restoreInputBar = jest.fn();
  const { result } = renderHook(() =>
    useChatController({
      llmManager: createLlmManager(),
      toolConfiguration,
      activeAgent: undefined,
      availableAgents: [],
      existingChatSessionId: "session",
      selectedDocuments: [],
      searchParams: new ReadonlyURLSearchParams(),
      resetInputBar: jest.fn(),
      restoreInputBar,
    })
  );

  await act(async () =>
    result.current.onSubmit({
      message: "Another question",
      mentions: [],
      currentMessageFiles: [],
      deepResearch: false,
    })
  );

  expect(restoreInputBar).toHaveBeenCalledWith({
    message: "Another question",
    mentions: [],
    files: [],
  });
  expect(toast.warning).toHaveBeenCalledWith("pendingUserInput.toast");
  expect(useToolRequestUi.getState().nudge).toBeNull();
  // Settlement loads the saved session, which replays the server's cards.
  expect(fetchSettledChatSession).toHaveBeenCalledWith("session");
  expect(refreshChatSession).not.toHaveBeenCalled();
});

test("abort releases a reader with packets queued before its first paint", async () => {
  const queued = Promise.withResolvers<void>();
  useChatSessionStore.setState({
    sessions: new Map(),
    currentSessionId: "session",
  });
  useChatSessionStore.getState().createSession("session");
  jest.mocked(sendMessage).mockImplementation(async function* () {
    yield { user_message_id: 11, reserved_assistant_message_id: 12 };
    yield {
      placement: { turn_index: 0, tab_index: 0 },
      obj: { type: "message_delta", content: "Buffered text" },
    };
    queued.resolve();
  });
  const { result, unmount } = renderHook(() =>
    useChatController({
      llmManager: createLlmManager(),
      toolConfiguration,
      activeAgent: undefined,
      availableAgents: [],
      existingChatSessionId: "session",
      selectedDocuments: [],
      searchParams: new ReadonlyURLSearchParams(),
      resetInputBar: jest.fn(),
      restoreInputBar: jest.fn(),
    })
  );
  let sending: Promise<void> | undefined;
  act(() => {
    sending = result.current.onSubmit({
      message: "Question",
      mentions: [],
      currentMessageFiles: [],
      deepResearch: false,
    });
  });
  await act(async () => {
    await queued.promise;
  });
  const session = useChatSessionStore.getState().sessions.get("session")!;
  session.abortController.abort();
  await sending;
  await expect(session.readerFinished).resolves.toBeUndefined();
  unmount();
});

test.each([false, true])(
  "tool preference persists after submission (%s)",
  async (accepted) => {
    useChatSessionStore.setState({
      sessions: new Map(),
      currentSessionId: "session",
    });
    useChatSessionStore
      .getState()
      .createSession("session", { incognito: true });
    jest.mocked(sendMessage).mockImplementation(async function* () {
      if (accepted)
        yield { user_message_id: 11, reserved_assistant_message_id: 12 };
      yield {
        error: "Request failed",
        error_code: "API_ERROR",
        is_retryable: true,
        stack_trace: "",
        details: {},
      };
    });
    const preferredAgent: MinimalAgent = {
      id: 7,
      name: "Agent",
      description: "",
      starter_messages: null,
      document_sets: [],
      is_public: true,
      is_listed: true,
      display_priority: null,
      is_featured: false,
      builtin_persona: false,
      owner: null,
      owner_group: null,
      user_permission: null,
      tools: [
        {
          id: 3,
          name: "SearchTool",
          display_name: "Search",
          description: "",
          in_code_tool_id: "SearchTool",
          definition: null,
          custom_headers: null,
          passthrough_auth: false,
          agent_creation_selectable: true,
          default_enabled: true,
          enabled: true,
          chat_selectable: true,
        },
      ],
    };
    const selectedConfiguration = { ...toolConfiguration, preferredToolId: 3 };
    const { result } = renderHook(() =>
      useChatController({
        llmManager: createLlmManager(),
        toolConfiguration: selectedConfiguration,
        activeAgent: preferredAgent,
        availableAgents: [],
        existingChatSessionId: "session",
        selectedDocuments: [],
        searchParams: new ReadonlyURLSearchParams(),
        resetInputBar: jest.fn(),
        restoreInputBar: jest.fn(),
      })
    );
    await act(async () =>
      result.current.onSubmit({
        message: "Question",
        mentions: [],
        currentMessageFiles: [],
        deepResearch: false,
      })
    );
    expect(sendMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        toolOptions: {
          allowed: null,
          preferred: { type: "capability", tool_id: 3 },
          internal_search_filters: expect.anything(),
        },
      })
    );
    expect(toolConfiguration.clearPreferredTool).not.toHaveBeenCalled();
    expect(toolConfiguration.setToolState).not.toHaveBeenCalled();
    await act(async () =>
      result.current.onSubmit({
        message: "Follow-up",
        mentions: [],
        currentMessageFiles: [],
        deepResearch: false,
      })
    );
    expect(sendMessage).toHaveBeenCalledTimes(2);
    expect(sendMessage).toHaveBeenLastCalledWith(
      expect.objectContaining({
        toolOptions: expect.objectContaining({
          preferred: { type: "capability", tool_id: 3 },
        }),
      })
    );
  }
);

test("a send after a failed turn continues after the failed response", async () => {
  jest.spyOn(console, "log").mockImplementation(() => {});
  useChatSessionStore.setState({
    sessions: new Map(),
    currentSessionId: "session",
  });
  useChatSessionStore.getState().createSession("session", { incognito: true });
  jest
    .mocked(sendMessage)
    .mockImplementationOnce(async function* () {
      yield { user_message_id: 11, reserved_assistant_message_id: 12 };
      yield {
        placement: { turn_index: 0 },
        obj: { type: "message_delta", content: "Partial answer" },
      };
      yield {
        error: "Provider failed",
        error_code: "API_ERROR",
        is_retryable: true,
        stack_trace: "",
        details: {},
      };
    })
    .mockImplementationOnce(async function* () {
      yield { user_message_id: 13, reserved_assistant_message_id: 14 };
      yield { placement: { turn_index: 0 }, obj: { type: "stop" } };
    });
  const { result } = renderHook(() =>
    useChatController({
      llmManager: createLlmManager(),
      toolConfiguration,
      activeAgent: undefined,
      availableAgents: [],
      existingChatSessionId: "session",
      selectedDocuments: [],
      searchParams: new ReadonlyURLSearchParams(),
      resetInputBar: jest.fn(),
      restoreInputBar: jest.fn(),
    })
  );
  for (const message of ["Question", "try again"]) {
    await act(async () =>
      result.current.onSubmit({
        message,
        mentions: [],
        currentMessageFiles: [],
        deepResearch: false,
      })
    );
  }

  expect(sendMessage).toHaveBeenLastCalledWith(
    expect.objectContaining({ message: "try again", parentMessageId: 12 })
  );
  const tree = useChatSessionStore
    .getState()
    .sessions.get("session")!.messageTree;
  const chain = getLatestMessageChain(tree);
  expect(chain.map((message) => [message.type, message.messageId])).toEqual([
    ["user", 11],
    ["error", 12],
    ["user", 13],
    ["assistant", 14],
  ]);
  expect(chain[2]!.parentNodeId).toBe(chain[1]!.nodeId);
});

function renderChatController(restoreInputBar = jest.fn()) {
  return renderHook(() =>
    useChatController({
      llmManager: createLlmManager(),
      toolConfiguration,
      activeAgent: undefined,
      availableAgents: [],
      existingChatSessionId: "session",
      selectedDocuments: [],
      searchParams: new ReadonlyURLSearchParams(),
      resetInputBar: jest.fn(),
      restoreInputBar,
    })
  );
}

test("an edit sends the composer's files and keeps a kept file's descriptor", async () => {
  useChatSessionStore.setState({
    sessions: new Map(),
    currentSessionId: "session",
  });
  useChatSessionStore.getState().createSession("session", { incognito: true });
  jest
    .mocked(sendMessage)
    .mockImplementationOnce(async function* () {
      yield { user_message_id: 11, reserved_assistant_message_id: 12 };
      yield { placement: { turn_index: 0 }, obj: { type: "stop" } };
    })
    .mockImplementationOnce(async function* () {
      yield { user_message_id: 13, reserved_assistant_message_id: 14 };
      yield { placement: { turn_index: 0 }, obj: { type: "stop" } };
    });
  const { result } = renderChatController();
  const file = (id: string): ProjectFile => ({
    id: `user-${id}`,
    file_id: `store-${id}`,
    name: `${id}.txt`,
    project_id: null,
    user_id: null,
    created_at: "",
    status: UserFileStatus.COMPLETED,
    file_type: "text/plain",
    last_accessed_at: "",
    chat_file_type: ChatFileType.PLAIN_TEXT,
    token_count: null,
    chunk_count: null,
  });
  await act(async () =>
    result.current.onSubmit({
      message: "Question",
      mentions: [],
      currentMessageFiles: [file("kept"), file("removed")],
      deepResearch: false,
    })
  );
  const [question] = getLatestMessageChain(
    useChatSessionStore.getState().sessions.get("session")!.messageTree
  );
  const kept = question!.files[0]!;

  await act(async () =>
    result.current.onSubmit({
      message: "Edited question",
      mentions: [],
      currentMessageFiles: [fileDescriptorToProjectFile(kept), file("added")],
      deepResearch: false,
      messageIdToResend: 11,
    })
  );

  expect(sendMessage).toHaveBeenLastCalledWith(
    expect.objectContaining({
      message: "Edited question",
      fileDescriptors: [
        kept,
        {
          id: "store-added",
          type: ChatFileType.PLAIN_TEXT,
          name: "added.txt",
          user_file_id: "user-added",
        },
      ],
    })
  );
});

test("a sent question shows its picks until the server records its skills", async () => {
  useChatSessionStore.setState({
    sessions: new Map(),
    currentSessionId: "session",
  });
  useChatSessionStore.getState().createSession("session");
  const saved = Promise.withResolvers<void>();
  jest.mocked(sendMessage).mockImplementationOnce(async function* () {
    await saved.promise;
    // The user can no longer use `gone`, so the server ignored it.
    yield {
      user_message_id: 11,
      reserved_assistant_message_id: 12,
      mentions: [
        { type: "skill", name: "code-review", version_id: "v-code-review" },
      ],
    };
    yield { placement: { turn_index: 0 }, obj: { type: "stop" } };
  });
  const { result } = renderChatController();
  const question = () => {
    const tree = useChatSessionStore
      .getState()
      .sessions.get("session")?.messageTree;
    return tree && getLatestMessageChain(tree)[0];
  };

  let sent: Promise<void> | undefined;
  act(() => {
    sent = result.current.onSubmit({
      message: "@code-review and @gone",
      mentions: [
        { type: "skill", name: "code-review" },
        { type: "skill", name: "gone" },
      ],
      currentMessageFiles: [],
      deepResearch: false,
    });
  });
  await waitFor(() =>
    expect(question()?.mentions).toEqual([
      { type: "skill", name: "code-review" },
      { type: "skill", name: "gone" },
    ])
  );
  expect(sendMessage).toHaveBeenCalledWith(
    expect.objectContaining({
      mentions: [
        { type: "skill", name: "code-review" },
        { type: "skill", name: "gone" },
      ],
    })
  );

  await act(async () => {
    saved.resolve();
    await sent;
  });
  expect(question()?.mentions).toEqual([
    { type: "skill", name: "code-review", version_id: "v-code-review" },
  ]);
});

// A setup failure, such as a rejected query hook, ends the stream with no IDs.
async function* rejectedSend() {
  yield {
    error: "Rejected before save",
    error_code: "BAD_REQUEST",
    is_retryable: false,
    stack_trace: "",
    details: {},
  };
}

test.each(["send", "regenerate"] as const)(
  "a %s the server rejects before saving leaves the tree as it was",
  async (kind) => {
    jest.spyOn(console, "log").mockImplementation(() => {});
    useChatSessionStore.setState({
      sessions: new Map(),
      currentSessionId: "session",
    });
    useChatSessionStore
      .getState()
      .createSession("session", { incognito: true });
    jest
      .mocked(sendMessage)
      .mockImplementationOnce(async function* () {
        yield { user_message_id: 11, reserved_assistant_message_id: 12 };
        yield { placement: { turn_index: 0 }, obj: { type: "stop" } };
      })
      .mockImplementationOnce(rejectedSend)
      .mockImplementationOnce(async function* () {
        yield { user_message_id: 13, reserved_assistant_message_id: 14 };
        yield { placement: { turn_index: 0 }, obj: { type: "stop" } };
      });
    const restoreInputBar = jest.fn();
    const { result } = renderChatController(restoreInputBar);
    const session = () =>
      useChatSessionStore.getState().sessions.get("session")!;
    await act(async () =>
      result.current.onSubmit({
        message: "Question",
        mentions: [],
        currentMessageFiles: [],
        deepResearch: false,
      })
    );
    const treeBefore = session().messageTree;
    const [question] = getLatestMessageChain(treeBefore);

    await act(async () =>
      result.current.onSubmit(
        kind === "send"
          ? {
              message: "Rejected @code-review question",
              mentions: [{ type: "skill", name: "code-review" }],
              currentMessageFiles: [],
              deepResearch: false,
            }
          : {
              message: "Question",
              mentions: [],
              currentMessageFiles: [],
              deepResearch: false,
              messageIdToResend: 11,
              regenerationRequest: { messageId: 12, parentMessage: question! },
            }
      )
    );
    expect(session().messageTree).toEqual(treeBefore);
    expect(session().uncaughtError).toMatchObject({
      error: "Rejected before save",
      errorCode: "BAD_REQUEST",
      isRetryable: false,
    });
    if (kind === "send") {
      expect(restoreInputBar).toHaveBeenCalledWith({
        message: "Rejected @code-review question",
        mentions: [{ type: "skill", name: "code-review" }],
        files: [],
      });
    } else {
      expect(restoreInputBar).not.toHaveBeenCalled();
    }

    await act(async () =>
      result.current.onSubmit({
        message: "Next",
        mentions: [],
        currentMessageFiles: [],
        deepResearch: false,
      })
    );
    expect(sendMessage).toHaveBeenLastCalledWith(
      expect.objectContaining({ message: "Next", parentMessageId: 12 })
    );
    expect(session().uncaughtError).toBeNull();
    expect(
      getLatestMessageChain(session().messageTree).map(
        (message) => message.messageId
      )
    ).toEqual([11, 12, 13, 14]);
  }
);

test("saved history keeps a failed turn and drops a rejected send", async () => {
  jest.spyOn(console, "log").mockImplementation(() => {});
  useChatSessionStore.setState({
    sessions: new Map(),
    currentSessionId: "session",
  });
  useChatSessionStore.getState().createSession("session");
  const savedQuestion: Message = {
    nodeId: 11,
    messageId: 11,
    message: "Question",
    type: "user",
    files: [],
    toolCall: null,
    parentNodeId: null,
    childrenNodeIds: [12],
    latestChildNodeId: 12,
    packets: [],
  };
  const savedFailure: Message = {
    nodeId: 12,
    messageId: 12,
    message: "Partial answer",
    type: "error",
    errorMessage: "Provider failed",
    responseStatus: "error",
    files: [],
    toolCall: null,
    parentNodeId: 11,
    childrenNodeIds: [],
    latestChildNodeId: null,
    packets: [],
  };
  // Every history load returns the saved failed turn.
  jest.mocked(processRawChatHistory).mockImplementation(
    () =>
      new Map([
        [11, savedQuestion],
        [12, savedFailure],
      ])
  );
  jest
    .mocked(sendMessage)
    .mockImplementationOnce(async function* () {
      yield { user_message_id: 11, reserved_assistant_message_id: 12 };
      yield {
        placement: { turn_index: 0 },
        obj: { type: "message_delta", content: "Partial answer" },
      };
      yield {
        error: "Provider failed",
        error_code: "API_ERROR",
        is_retryable: true,
        stack_trace: "",
        details: {},
      };
    })
    .mockImplementationOnce(rejectedSend)
    .mockImplementationOnce(async function* () {
      yield { user_message_id: 13, reserved_assistant_message_id: 14 };
      yield { placement: { turn_index: 0 }, obj: { type: "stop" } };
    });
  const { result } = renderChatController();
  const chain = () =>
    getLatestMessageChain(
      useChatSessionStore.getState().sessions.get("session")!.messageTree
    ).map((message) => [message.type, message.messageId]);
  for (const message of ["Question", "Rejected question"]) {
    await act(async () =>
      result.current.onSubmit({
        message,
        mentions: [],
        currentMessageFiles: [],
        deepResearch: false,
      })
    );
  }
  expect(fetchSettledChatSession).toHaveBeenCalledTimes(2);
  expect(chain()).toEqual([
    ["user", 11],
    ["error", 12],
  ]);
  expect(
    useChatSessionStore.getState().sessions.get("session")?.uncaughtError?.error
  ).toBe("Rejected before save");

  await act(async () =>
    result.current.onSubmit({
      message: "try again",
      mentions: [],
      currentMessageFiles: [],
      deepResearch: false,
    })
  );
  expect(sendMessage).toHaveBeenLastCalledWith(
    expect.objectContaining({ message: "try again", parentMessageId: 12 })
  );
  jest.mocked(processRawChatHistory).mockImplementation(() => new Map());
});

test("a failed preference write drops the send and the next send retries it", async () => {
  jest.spyOn(console, "log").mockImplementation(() => {});
  useChatSessionStore.setState({
    sessions: new Map(),
    currentSessionId: "session",
  });
  useChatSessionStore.getState().createSession("session", { incognito: true });
  jest
    .mocked(sendMessage)
    .mockImplementationOnce(async function* () {
      yield {
        user_message_id: 11,
        responses: [
          { message_id: 12, model_name: "First" },
          { message_id: 13, model_name: "Second" },
        ],
      };
      for (const model_index of [0, 1]) {
        yield {
          placement: { turn_index: 0, tab_index: 0, model_index },
          obj: { type: "message_delta", content: `Answer ${model_index}` },
        };
        yield {
          placement: { turn_index: 0, tab_index: 0, model_index },
          obj: { type: "stop" },
        };
      }
    })
    .mockImplementationOnce(async function* () {
      yield { user_message_id: 14, reserved_assistant_message_id: 15 };
      yield { placement: { turn_index: 0 }, obj: { type: "stop" } };
    });
  jest
    .mocked(setPreferredResponse)
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Not saved" }), { status: 500 })
    )
    .mockResolvedValueOnce(new Response(null, { status: 200 }));
  const restoreInputBar = jest.fn();
  const { result } = renderChatController(restoreInputBar);
  const session = () => useChatSessionStore.getState().sessions.get("session")!;
  await act(async () =>
    result.current.onSubmit({
      message: "Compare answers",
      mentions: [],
      currentMessageFiles: [],
      deepResearch: false,
      selectedModels: ["First", "Second"].map((name) => ({
        name: "provider",
        provider: "openai",
        modelName: name,
        modelConfigurationId: null,
        displayName: name,
      })),
    })
  );
  const userNodeId = getLatestMessageChain(session().messageTree)[0]!.nodeId;

  await act(async () =>
    result.current.onSubmit({
      message: "Follow-up",
      mentions: [],
      currentMessageFiles: [],
      deepResearch: false,
    })
  );
  expect(sendMessage).toHaveBeenCalledTimes(1);
  expect(restoreInputBar).toHaveBeenCalledWith({
    message: "Follow-up",
    mentions: [],
    files: [],
  });
  expect(session().uncaughtError?.error).toBe("Not saved");
  expect(
    getLatestMessageChain(session().messageTree).map(
      (message) => message.messageId
    )
  ).toEqual([11, 13]);
  expect(
    session().messageTree.get(userNodeId)?.preferredResponseId
  ).toBeUndefined();

  await act(async () =>
    result.current.onSubmit({
      message: "Follow-up",
      mentions: [],
      currentMessageFiles: [],
      deepResearch: false,
    })
  );
  expect(setPreferredResponse).toHaveBeenCalledTimes(2);
  expect(setPreferredResponse).toHaveBeenLastCalledWith(11, 13);
  expect(sendMessage).toHaveBeenLastCalledWith(
    expect.objectContaining({ message: "Follow-up", parentMessageId: 13 })
  );
});

const sentTurn = { user_message_id: 11, reserved_assistant_message_id: 12 };

/** How each run of the session ended, as the sidebar watcher sees it. */
function recordRunEndings(): { endings: string[]; stop: () => void } {
  const endings: string[] = [];
  const stop = useChatSessionStore.subscribe((state, prev) => {
    const session = state.sessions.get("session");
    const before = prev.sessions.get("session");
    if (session && before && isWorking(before) && !isWorking(session)) {
      const ended = endedRunStatus(session);
      if (ended) endings.push(ended);
    }
  });
  return { endings, stop };
}

test.each<{
  name: string;
  send: () => AsyncGenerator<PacketType>;
  ended: "failed" | "done";
}>([
  {
    name: "an INIT_FAILED body",
    send: async function* () {
      yield {
        error: "Failed to initialize the chat",
        error_code: "INIT_FAILED",
        is_retryable: true,
        stack_trace: "",
        details: {},
      };
    },
    ended: "failed",
  },
  {
    name: "an HTTP rejection",
    send: async function* () {
      yield* [];
      throw new ChatSendRejectedError("Bad request");
    },
    ended: "failed",
  },
  {
    name: "an HTTP server error",
    send: async function* () {
      yield* [];
      throw new Error("HTTP error! status: 502");
    },
    ended: "failed",
  },
  {
    name: "a stream error packet",
    send: async function* () {
      yield sentTurn;
      yield {
        error: "Provider failed",
        error_code: "API_ERROR",
        is_retryable: true,
        stack_trace: "",
        details: {},
      };
    },
    ended: "failed",
  },
  {
    name: "a dropped stream",
    send: async function* () {
      yield sentTurn;
      throw new Error("network error");
    },
    ended: "failed",
  },
  {
    name: "a complete answer",
    send: async function* () {
      yield sentTurn;
      yield { placement: { turn_index: 0 }, obj: { type: "stop" } };
    },
    ended: "done",
  },
])("a run that ends with $name shows $ended", async ({ send, ended }) => {
  jest.spyOn(console, "log").mockImplementation(() => {});
  jest.spyOn(console, "error").mockImplementation(() => {});
  useChatSessionStore.setState({
    sessions: new Map(),
    currentSessionId: "session",
  });
  useChatSessionStore.getState().createSession("session");
  jest.mocked(sendMessage).mockImplementationOnce(send);
  const runs = recordRunEndings();
  const { result } = renderChatController();
  await act(async () =>
    result.current.onSubmit({
      message: "Question",
      mentions: [],
      currentMessageFiles: [],
      deepResearch: false,
    })
  );
  runs.stop();
  expect(runs.endings).toEqual([ended]);
});

test("a run the user cancels records no outcome", async () => {
  useChatSessionStore.setState({
    sessions: new Map(),
    currentSessionId: "session",
  });
  useChatSessionStore.getState().createSession("session", { incognito: true });
  const stopped = Promise.withResolvers<void>();
  global.fetch = jest.fn(async () => {
    stopped.resolve();
    return new Response(null, { status: 200 });
  });
  jest.mocked(sendMessage).mockImplementationOnce(async function* () {
    yield sentTurn;
    await stopped.promise;
    yield {
      placement: { turn_index: 0 },
      obj: { type: "stop", stop_reason: StopReason.USER_CANCELLED },
    };
  });
  const runs = recordRunEndings();
  const { result } = renderChatController();
  let sent: Promise<void> | undefined;
  act(() => {
    sent = result.current.onSubmit({
      message: "Question",
      mentions: [],
      currentMessageFiles: [],
      deepResearch: false,
    });
  });
  await waitFor(() =>
    expect(
      useChatSessionStore.getState().sessions.get("session")?.chatState
    ).toBe("streaming")
  );
  await act(async () => {
    await result.current.stopGenerating();
    await sent;
  });
  runs.stop();
  expect(runs.endings).toEqual([]);
});

test("Stop preserves a rejection when it releases the composer first", async () => {
  const reject = Promise.withResolvers<void>();
  jest.spyOn(console, "log").mockImplementation(() => {});
  useChatSessionStore.setState({
    sessions: new Map(),
    currentSessionId: "session",
  });
  useChatSessionStore.getState().createSession("session", { incognito: true });
  jest
    .mocked(sendMessage)
    .mockReset()
    .mockImplementationOnce(async function* () {
      await reject.promise;
      yield* rejectedSend();
    });
  const { result } = renderChatController();
  let send: Promise<void> | undefined;
  act(() => {
    send = result.current.onSubmit({
      message: "Rejected question",
      mentions: [],
      currentMessageFiles: [],
      deepResearch: false,
    });
  });
  await waitFor(() => expect(sendMessage).toHaveBeenCalled());

  await act(async () => {
    const stop = result.current.stopGenerating();
    reject.resolve();
    await stop;
    expect(
      useChatSessionStore.getState().sessions.get("session")
    ).toMatchObject({
      chatState: "input",
      uncaughtError: {
        error: "Rejected before save",
        errorCode: "BAD_REQUEST",
      },
    });
    await send;
  });
});
