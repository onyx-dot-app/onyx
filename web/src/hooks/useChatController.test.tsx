import { act, renderHook, waitFor } from "@testing-library/react";
import { ReadonlyURLSearchParams } from "next/navigation";
import useChatController from "@/hooks/useChatController";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { createChatSession, sendMessage } from "@/app/app/services/lib";
import type { LlmManager } from "@/lib/hooks";
import { waitForChatSessionIdle } from "@/lib/chat/sessionReadiness";
import type { ToolConfigurationHandle } from "@/lib/tools/hooks";

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
jest.mock("@opal/layouts", () => ({ toast: { error: jest.fn() } }));
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
  usePinnedAgents: () => ({ pinnedAgents: [], togglePinnedAgent: jest.fn() }),
}));
jest.mock("@/lib/projects/providers", () => ({
  useProjectsContext: () => ({
    fetchProjects: jest.fn(),
    setCurrentMessageFiles: jest.fn(),
    beginUpload: jest.fn(),
  }),
}));
jest.mock("@/providers/IncognitoProvider", () => ({
  useIncognito: () => ({
    incognitoEnabledRef: { current: false },
    incognitoSessionId: null,
  }),
}));
jest.mock("@/app/app/services/lib", () => ({
  updateLlmOverrideForChatSession: jest.fn(),
  processRawChatHistory: jest.fn(() => new Map()),
  sendMessage: jest.fn(),
  createChatSession: jest.fn(),
  buildChatUrl: () => "/app?chatId=session",
  ChatSendRejectedError: class extends Error {},
}));
jest.mock("@/lib/chat/sessionReadiness", () => ({
  waitForChatSessionIdle: jest.fn(async () => {}),
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
  clearForcedTool: jest.fn(),
  forcedToolId: null,
  disabledToolIds: [],
  ready: true,
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
  "Stop during preference persistence prevents a pending send (new session: %s)",
  async (isNewSession) => {
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
    const { result } = renderHook(() =>
      useChatController({
        llmManager,
        toolConfiguration,
        activeAgent: undefined,
        availableAgents: [],
        existingChatSessionId: isNewSession ? null : "session",
        selectedDocuments: [],
        searchParams: new ReadonlyURLSearchParams(),
        resetInputBar: jest.fn(),
        restoreInputBar: jest.fn(),
      })
    );

    let pendingSend: Promise<void> | undefined;
    act(() => {
      pendingSend = result.current.onSubmit({
        message: "Do not send this after Stop",
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
    await act(async () => result.current.stopGenerating());
    expect(
      useChatSessionStore.getState().sessions.get("session")?.chatState
    ).toBe("input");

    await act(async () => {
      preferences.resolve();
      await pendingSend;
    });
    expect(sendMessage).not.toHaveBeenCalled();
    expect(
      useChatSessionStore.getState().sessions.get("session")?.chatState
    ).toBe("input");
  }
);

test("Stop drains multi-model packets and finishes every panel before releasing incognito input", async () => {
  const tail = Promise.withResolvers<void>();
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
      "/api/chat/stop-chat-session/session?stream_id=11",
      expect.objectContaining({ method: "POST" })
    )
  );
  expect(waitForChatSessionIdle).not.toHaveBeenCalled();
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
