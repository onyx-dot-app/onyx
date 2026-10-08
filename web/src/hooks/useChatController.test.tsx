import { act, renderHook } from "@testing-library/react";
import { ReadonlyURLSearchParams } from "next/navigation";
import useChatController from "@/hooks/useChatController";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { sendMessage } from "@/app/app/services/lib";
import type { LlmManager } from "@/lib/hooks";
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
  jest.clearAllMocks();
});

test("Stop during preference persistence prevents the pending send from dispatching afterward", async () => {
  const preferences = Promise.withResolvers<void>();
  const llmManager: LlmManager = {
    currentLlm: { name: "provider", provider: "openai", modelName: "model" },
    updateCurrentLlm: jest.fn(),
    temperature: 0,
    updateTemperature: jest.fn(),
    temperatureExplicitlySet: false,
    reasoningEffort: null,
    updateReasoningEffort: jest.fn(),
    hasBoundSession: true,
    persistOverrides: jest.fn(() => preferences.promise),
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
      loadMore: jest.fn(async () => {}),
      search: jest.fn(async () => false),
      searchHasMore: false,
      loadMoreSearch: jest.fn(async () => {}),
    },
    isLoadingProviders: false,
    hasAnyProvider: false,
  };
  global.fetch = jest.fn(async () => new Response(null, { status: 200 }));
  useChatSessionStore.setState({
    sessions: new Map(),
    currentSessionId: "session",
  });
  useChatSessionStore.getState().createSession("session");
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
  expect(llmManager.persistOverrides).toHaveBeenCalledWith("session");
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
});
