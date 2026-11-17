import { renderHook, act, waitFor, cleanup } from "@testing-library/react";
import {
  type SourceMetadata,
  ValidSources,
} from "@/lib/connectors/types/source";
import { flushToolOptions, useToolConfiguration } from "@/lib/tools/hooks";
import useDeepResearchToggle from "@/hooks/useDeepResearchToggle";
import { effectiveChatPreference } from "@/lib/plugins/chat";
import type { MinimalAgent } from "@/lib/agents/types";
import { DEFAULT_AGENT_ID } from "@/lib/constants";
import type { ChatToolOptions, ToolSnapshot } from "@/lib/tools/types";
import type { User } from "@/lib/types";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import {
  ChatSessionSharedStatus,
  type BackendChatSession,
} from "@/app/app/types";
import { toast } from "@opal/layouts";
import {
  selectedSourcesFrom,
  buildFilters,
  toggleSourceSelection,
  normalizeSourceSelection,
} from "@/lib/searchFilters/utils";

// Mutable so a test can move the composer between chats; the hook re-keys
// from what useAppPosition reports on each render.
let mockChatId: string | null = "abc";

jest.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));
jest.mock("@/lib/navigation/hooks", () => ({
  useAppPosition: () => ({
    chat: () => mockChatId,
    agent: () => null,
    project: () => null,
  }),
}));

let mockActiveAgent: MinimalAgent | undefined;
jest.mock("@/lib/agents/hooks", () => ({
  useActiveAgent: () => mockActiveAgent,
}));

let mockIncognitoEnabled = false;
jest.mock("@/providers/IncognitoProvider", () => ({
  useIncognito: () => ({ incognitoEnabled: mockIncognitoEnabled }),
}));

const SIGNED_IN: Pick<User, "id" | "email" | "is_anonymous_user"> = {
  id: "user",
  email: "user@example.com",
  is_anonymous_user: false,
};
let mockUser: Pick<User, "id" | "email" | "is_anonymous_user"> | null =
  SIGNED_IN;
// The agent's plugins and the plugins the user turned off for it.
let mockPluginIds: string[] | null = [];
let mockDisabledPluginIds: string[] = [];
// The agents whose plugins and preferences the composer read.
let mockReadAgentIds: (number | undefined)[] = [];
const mockSetPluginsDisabled = jest.fn(() => Promise.resolve());
jest.mock("@/lib/plugins/hooks", () => ({
  useAgentChatPlugins: (agentId: number | undefined) => {
    mockReadAgentIds.push(agentId);
    return {
      pluginIds: mockPluginIds,
      plugins: [],
      isLoading: false,
      error: undefined,
      refresh: jest.fn(),
    };
  },
  useAgentPluginPreferences: () => ({
    loaded: true,
    disabledPluginIds: (agentId: number) => {
      mockReadAgentIds.push(agentId);
      return mockDisabledPluginIds;
    },
    setPluginsDisabled: mockSetPluginsDisabled,
  }),
}));
jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({ user: mockUser }),
}));

beforeEach(() => {
  sessionStorage.clear();
  mockChatId = "abc";
  mockIncognitoEnabled = false;
  mockActiveAgent = undefined;
  mockUser = SIGNED_IN;
  mockPluginIds = [];
  mockDisabledPluginIds = [];
  mockReadAgentIds = [];
  mockSetPluginsDisabled.mockClear();
  echoSaves();
});

// A composer that closes sends its due save, so each test's saves finish
// against its own fetch mock.
afterEach(async () => {
  cleanup();
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  jest.restoreAllMocks();
});

function source(internalName: ValidSources, uniqueKey: string): SourceMetadata {
  return { internalName, uniqueKey } as SourceMetadata;
}

const NOTION = source(ValidSources.Notion, "notion");
const SLACK = source(ValidSources.Slack, "slack");

const tool = (id: number): ToolSnapshot => ({
  id,
  name: `tool_${id}`,
  display_name: `Tool ${id}`,
  description: "",
  definition: null,
  custom_headers: null,
  in_code_tool_id: null,
  passthrough_auth: false,
  mcp_server_id: null,
  enabled: true,
  chat_selectable: true,
  agent_creation_selectable: true,
  default_enabled: true,
});

const AGENT: MinimalAgent = {
  id: 7,
  name: "Agent",
  description: "",
  tools: [
    { ...tool(1), in_code_tool_id: "SearchTool" },
    { ...tool(2), in_code_tool_id: "WebSearchTool" },
  ],
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
};

const NO_FILTERS = {
  source_type: null,
  document_set: null,
  updated_at_range: null,
  tags: [],
};

/** Opens existing chats whose details carry these saved selections. */
function openSavedChats(
  saved: Record<string, ChatToolOptions | null> = { abc: null },
  incognito: boolean = false
): void {
  mockActiveAgent = AGENT;
  useChatSessionStore.setState({ sessions: new Map(), currentSessionId: null });
  for (const [chatSessionId, toolOptions] of Object.entries(saved)) {
    useChatSessionStore
      .getState()
      .createSession(chatSessionId, { incognito, toolOptions });
  }
}

/** A chat detail as the server returns it, with no saved selection. */
function staleChatDetail(chatSessionId: string): BackendChatSession {
  return {
    chat_session_id: chatSessionId,
    description: "Chat",
    persona_id: AGENT.id,
    persona_name: AGENT.name,
    messages: [],
    time_created: "2026-01-01T00:00:00Z",
    time_updated: "2026-01-01T00:00:00Z",
    shared_status: ChatSessionSharedStatus.Private,
    current_temperature_override: null,
    current_reasoning_effort_override: null,
    owner_name: null,
    packets: [],
    tool_options: null,
  };
}

/** Answers each PATCH with the selection it sent, as a chat that keeps content does. */
function echoSaves(
  answer: (sent: ChatToolOptions) => ChatToolOptions | null = (sent) => sent
): jest.SpyInstance {
  return jest
    .spyOn(global, "fetch")
    .mockImplementation(async (_url, init) =>
      init?.method === "PATCH"
        ? new Response(JSON.stringify(answer(JSON.parse(String(init.body)))))
        : new Response(JSON.stringify([]))
    );
}

function patchesOf(fetchSpy: jest.SpyInstance): [unknown, RequestInit][] {
  return fetchSpy.mock.calls.filter(
    ([, init]: [unknown, RequestInit | undefined]) => init?.method === "PATCH"
  );
}

describe("useToolConfiguration: a chat that does not exist yet", () => {
  test("the pre-filters flat shape still reads as the tool map", () => {
    sessionStorage.setItem(
      "onyx:tools:new:7",
      JSON.stringify({ 1: "preferred", 2: "disabled" })
    );
    const { result } = renderHook(() => useToolConfiguration(7));

    expect(result.current.preferredToolId).toBe(1);
    expect(result.current.disabledToolIds).toEqual([2]);
    expect(result.current.filters.selectedSources).toBeNull();
    expect(result.current.filters.timeRange).toBeNull();
  });

  test.each([false, true])(
    "obsolete forced selections are dropped in stored shape (nested=%s)",
    (nested) => {
      sessionStorage.setItem(
        "onyx:tools:new:7",
        JSON.stringify(
          nested
            ? { tools: { 1: "forced", 2: "disabled" } }
            : { 1: "forced", 2: "disabled" }
        )
      );
      const { result } = renderHook(() => useToolConfiguration(7));
      expect(result.current.preferredToolId).toBeNull();
      expect(result.current.disabledToolIds).toEqual([2]);
    }
  );

  test("a hand-off to a new chat carries the filters and is read once", () => {
    const { result, unmount } = renderHook(() => useToolConfiguration(7));
    act(() => {
      result.current.setFilters((current) => ({
        ...current,
        selectedSources: ["notion"],
      }));
    });
    act(() => result.current.handOffToNewChatWith(7));
    unmount();

    const { result: reread, unmount: leave } = renderHook(() =>
      useToolConfiguration(7)
    );
    expect(reread.current.filters.selectedSources).toEqual(["notion"]);
    leave();
    const { result: again } = renderHook(() => useToolConfiguration(7));
    expect(again.current.filters.selectedSources).toBeNull();
  });
});

describe("useToolConfiguration: an existing chat", () => {
  test("reads its selection from the chat's details, not from storage", () => {
    sessionStorage.setItem(
      "onyx:tools:chat:abc",
      JSON.stringify({ tools: { 2: "preferred" } })
    );
    openSavedChats({
      abc: {
        allowed: [{ type: "capability", tool_id: 1 }],
        preferred: { type: "capability", tool_id: 1 },
        internal_search_filters: {
          source_type: ["notion"],
          document_set: ["Handbook"],
          updated_at_range: { start: "2026-01-01T00:00:00Z", end: null },
          tags: [{ tag_key: "team", tag_value: "sales" }],
        },
      },
    });
    const { result } = renderHook(() => useToolConfiguration());

    expect(result.current.ready).toBe(true);
    expect(result.current.preferredToolId).toBe(1);
    expect(result.current.disabledToolIds).toEqual([2]);
    expect(result.current.filters).toEqual({
      selectedSources: ["notion"],
      documentSets: ["Handbook"],
      tags: [{ tag_key: "team", tag_value: "sales" }],
      timeRange: { from: "2026-01-01T00:00:00Z" },
    });
  });

  test("keeps the saved selection for a send while the plugin catalogs load", () => {
    mockPluginIds = null;
    const saved: ChatToolOptions = {
      allowed: [
        { type: "capability", tool_id: 1 },
        { type: "plugin", plugin_id: "plugin-1" },
      ],
      preferred: null,
      internal_search_filters: { ...NO_FILTERS, source_type: ["notion"] },
    };
    openSavedChats({ abc: saved });
    const { result } = renderHook(() => useToolConfiguration());

    expect(result.current.ready).toBe(false);
    expect(result.current.allowed).toEqual(saved.allowed);
    expect(result.current.disabledToolIds).toEqual([2]);
    expect(result.current.filters.selectedSources).toEqual(["notion"]);
  });

  test("holds a send until its saved options load", () => {
    openSavedChats({});
    const { result, rerender } = renderHook(() => useToolConfiguration());
    expect(result.current.optionsLoaded).toBe(false);

    act(() =>
      useChatSessionStore.getState().createSession("abc", {
        incognito: false,
        toolOptions: {
          allowed: [{ type: "capability", tool_id: 1 }],
          preferred: null,
          internal_search_filters: NO_FILTERS,
        },
      })
    );
    rerender();
    expect(result.current.optionsLoaded).toBe(true);
  });

  test("drops writes until its details load", () => {
    openSavedChats({});
    const { result, rerender } = renderHook(() => useToolConfiguration());
    expect(result.current.ready).toBe(false);
    act(() => result.current.toggleToolState(2, "disabled"));
    expect(result.current.disabledToolIds).toEqual([]);

    act(() =>
      useChatSessionStore
        .getState()
        .createSession("abc", { incognito: false, toolOptions: null })
    );
    rerender();
    expect(result.current.ready).toBe(true);
    expect(result.current.disabledToolIds).toEqual([]);
  });

  test("each chat keeps its own saved selection", async () => {
    openSavedChats({ abc: null, other: null });
    const fetchSpy = echoSaves();
    const { result, rerender } = renderHook(() => useToolConfiguration());
    act(() => {
      result.current.setFilters((current) => ({
        ...current,
        documentSets: ["Handbook"],
      }));
    });
    act(() => result.current.toggleToolState(1, "preferred"));
    await waitFor(() => expect(patchesOf(fetchSpy)).toHaveLength(1));
    await waitFor(() =>
      expect(
        useChatSessionStore.getState().sessions.get("abc")?.toolOptions
      ).not.toBeNull()
    );

    mockChatId = "other";
    rerender();
    expect(result.current.filters.documentSets).toEqual([]);
    expect(result.current.preferredToolId).toBeNull();

    mockChatId = "abc";
    rerender();
    expect(result.current.filters.documentSets).toEqual(["Handbook"]);
    expect(result.current.preferredToolId).toBe(1);
  });

  test("editing sources never touches a preferred pin", () => {
    openSavedChats();
    const { result } = renderHook(() => useToolConfiguration());
    act(() => result.current.toggleToolState(1, "preferred"));
    act(() => {
      result.current.setFilters((current) => ({
        ...current,
        selectedSources: [],
      }));
    });
    act(() => {
      result.current.setFilters((current) => ({
        ...current,
        selectedSources: null,
      }));
    });

    expect(result.current.preferredToolId).toBe(1);
  });

  test("tool state changes never touch the source selection", () => {
    openSavedChats();
    const { result } = renderHook(() => useToolConfiguration());
    act(() => {
      result.current.setFilters((current) => ({
        ...current,
        selectedSources: ["notion"],
      }));
    });
    act(() => result.current.toggleToolState(1, "preferred"));
    act(() => result.current.toggleToolState(1, "preferred"));
    act(() => result.current.toggleToolState(2, "disabled"));

    expect(result.current.filters.selectedSources).toEqual(["notion"]);
  });
});

describe("selectedSourcesFrom: positive-selection semantics", () => {
  beforeEach(() => openSavedChats());

  const configured = [NOTION, SLACK];

  test("an untouched selection means no source filter at all", () => {
    const { result } = renderHook(() => useToolConfiguration());
    const selected = selectedSourcesFrom(result.current.filters, configured);

    expect(selected).toBeNull();
    expect(buildFilters(selected, [], null, []).source_type).toBeNull();
  });

  test("an explicit selection narrows to those sources", () => {
    const { result } = renderHook(() => useToolConfiguration());
    act(() => {
      result.current.setFilters((current) => ({
        ...current,
        selectedSources: ["notion"],
      }));
    });
    const selected = selectedSourcesFrom(result.current.filters, configured);

    expect(selected).toEqual([NOTION]);
    expect(buildFilters(selected, [], null, []).source_type).toEqual([
      ValidSources.Notion,
    ]);
  });

  test("selecting nothing sends an explicitly empty list", () => {
    const { result } = renderHook(() => useToolConfiguration());
    act(() => {
      result.current.setFilters((current) => ({
        ...current,
        selectedSources: [],
      }));
    });
    const selected = selectedSourcesFrom(result.current.filters, configured);

    expect(selected).toEqual([]);
    expect(buildFilters(selected, [], null, []).source_type).toEqual([]);
  });

  test("a selection naming a removed connector drops it", () => {
    const { result } = renderHook(() => useToolConfiguration());
    act(() => {
      result.current.setFilters((current) => ({
        ...current,
        selectedSources: ["notion", "gone"],
      }));
    });
    const selected = selectedSourcesFrom(result.current.filters, configured);

    expect(selected).toEqual([NOTION]);
  });
});

describe("toggleSourceSelection: edit-boundary normalization", () => {
  const keys = ["notion", "slack"];

  test("the first toggle materialises the untouched default", () => {
    expect(toggleSourceSelection(null, "slack", keys)).toEqual(["notion"]);
  });

  test("re-covering every configured source collapses to the sentinel", () => {
    expect(toggleSourceSelection(["notion"], "slack", keys)).toBeNull();
  });

  test("toggling the last source off leaves the explicit empty set", () => {
    expect(toggleSourceSelection(["notion"], "notion", keys)).toEqual([]);
  });

  test("a covering write from any surface collapses to the sentinel", () => {
    expect(normalizeSourceSelection(["slack", "notion"], keys)).toBeNull();
    expect(normalizeSourceSelection(["notion"], keys)).toEqual(["notion"]);
    expect(normalizeSourceSelection([], keys)).toEqual([]);
  });
});

test("a send's chosen tools carry over to the chat it creates and are saved there", async () => {
  openSavedChats({});
  mockChatId = null;
  const fetchSpy = echoSaves();
  const { result, rerender, unmount } = renderHook(() =>
    useToolConfiguration()
  );
  act(() => {
    result.current.setToolState(1, () => "preferred");
    result.current.setToolState(2, () => "disabled");
  });
  act(() => result.current.handOffTo("created"));
  mockChatId = "created";
  rerender();
  expect(result.current.ready).toBe(true);
  expect(result.current.preferredToolId).toBe(1);
  expect(result.current.disabledToolIds).toEqual([2]);
  await waitFor(() => expect(patchesOf(fetchSpy)).toHaveLength(1));
  const [url, init] = patchesOf(fetchSpy)[0]!;
  expect(url).toBe("/api/chat/chat-session/created/tool-options");
  expect(JSON.parse(String(init.body))).toEqual({
    allowed: [{ type: "capability", tool_id: 1 }],
    preferred: { type: "capability", tool_id: 1 },
    internal_search_filters: NO_FILTERS,
  });
  await waitFor(() =>
    expect(
      useChatSessionStore.getState().sessions.get("created")?.toolOptions
    ).toBeTruthy()
  );
  unmount();

  const reloaded = renderHook(() => useToolConfiguration());
  expect(reloaded.result.current.preferredToolId).toBe(1);
  expect(reloaded.result.current.disabledToolIds).toEqual([2]);
});

test("Deep Research and a tool preference are mutually exclusive", () => {
  openSavedChats();
  const { result } = renderHook(() => {
    const configuration = useToolConfiguration();
    const research = useDeepResearchToggle({
      chatSessionId: "abc",
      agentId: 7,
      toolConfiguration: configuration,
    });
    return { configuration, research };
  });
  act(() => result.current.configuration.setToolState(1, () => "preferred"));
  act(() => result.current.research.toggleDeepResearch());
  expect(result.current.configuration.preferredToolId).toBeNull();
  expect(result.current.research.deepResearchEnabled).toBe(true);
  act(() => result.current.configuration.setToolState(2, () => "preferred"));
  expect(result.current.research.deepResearchEnabled).toBe(false);
  expect(result.current.configuration.preferredToolId).toBe(2);
});

test("incognito masks Deep Research and leaving incognito restores it", () => {
  const { result, rerender } = renderHook(() =>
    useDeepResearchToggle({
      chatSessionId: "abc",
      agentId: 1,
      toolConfiguration: {
        preferredToolId: null,
        clearPreferredTool: jest.fn(),
      },
    })
  );
  act(() => result.current.toggleDeepResearch());
  expect(result.current.deepResearchEnabled).toBe(true);
  mockIncognitoEnabled = true;
  rerender();
  expect(result.current.deepResearchEnabled).toBe(false);
  mockIncognitoEnabled = false;
  rerender();
  expect(result.current.deepResearchEnabled).toBe(true);
});

test("a tool change saves only the tools, so the saved filters stay as they are", async () => {
  const saved: ChatToolOptions = {
    allowed: null,
    preferred: null,
    internal_search_filters: {
      ...NO_FILTERS,
      source_type: ["notion"],
      document_set: ["Handbook"],
    },
  };
  openSavedChats({ abc: saved });
  // The server merges the fields a save sets into what it keeps.
  const fetchSpy = echoSaves((sent) => ({ ...saved, ...sent }));
  const { result } = renderHook(() => useToolConfiguration());
  expect(result.current.ready).toBe(true);

  act(() => {
    result.current.toggleToolState(2, "disabled");
    result.current.toggleToolState(1, "preferred");
  });
  await waitFor(() => expect(patchesOf(fetchSpy)).toHaveLength(1));
  const [url, init] = patchesOf(fetchSpy)[0]!;
  expect(url).toBe("/api/chat/chat-session/abc/tool-options");
  // The source roster plays no part, so an unloaded one cannot clear the
  // saved sources.
  expect(JSON.parse(String(init.body))).toEqual({
    allowed: [{ type: "capability", tool_id: 1 }],
    preferred: { type: "capability", tool_id: 1 },
  });
  await waitFor(() =>
    expect(
      useChatSessionStore.getState().sessions.get("abc")?.toolOptionsEdits
    ).toBeUndefined()
  );
  expect(result.current.filters.selectedSources).toEqual(["notion"]);
  expect(result.current.filters.documentSets).toEqual(["Handbook"]);
});

test("a tool change keeps a saved preferred tool that the composer cannot offer", async () => {
  // A send drops a preferred tool that it cannot build; the saved choice
  // stays.
  const mcpTool: ToolSnapshot = { ...tool(3), mcp_server_id: 9 };
  const saved: ChatToolOptions = {
    allowed: null,
    preferred: { type: "capability", tool_id: mcpTool.id },
    internal_search_filters: NO_FILTERS,
  };
  openSavedChats({ abc: saved });
  mockActiveAgent = {
    ...AGENT,
    id: DEFAULT_AGENT_ID,
    tools: [...AGENT.tools, mcpTool],
  };
  const fetchSpy = echoSaves((sent) => ({ ...saved, ...sent }));
  const { result } = renderHook(() => useToolConfiguration());
  expect(result.current.ready).toBe(true);

  act(() => {
    result.current.toggleToolState(2, "disabled");
  });
  await waitFor(() => expect(patchesOf(fetchSpy)).toHaveLength(1));
  const [, init] = patchesOf(fetchSpy)[0]!;
  expect(JSON.parse(String(init.body))).toEqual({
    allowed: [{ type: "capability", tool_id: 1 }],
    preferred: { type: "capability", tool_id: mcpTool.id },
  });
});

test("a saved preferred action stays through a plugin switch and a tool pin releases it", async () => {
  mockPluginIds = ["plugin-a", "plugin-b"];
  const action = {
    type: "action",
    plugin_id: "plugin-a",
    action: "create_issue",
  } as const;
  const saved: ChatToolOptions = {
    allowed: null,
    preferred: action,
    internal_search_filters: NO_FILTERS,
  };
  openSavedChats({ abc: saved });
  const fetchSpy = echoSaves((sent) => ({ ...saved, ...sent }));
  const { result } = renderHook(() => useToolConfiguration());
  expect(result.current.preferredAction).toEqual(action);

  act(() => result.current.setPluginEnabled(["plugin-b"], false));
  await waitFor(() => expect(patchesOf(fetchSpy)).toHaveLength(1));
  expect(JSON.parse(String(patchesOf(fetchSpy)[0]![1].body)).preferred).toEqual(
    action
  );

  act(() => result.current.toggleToolState(1, "preferred"));
  await waitFor(() => expect(patchesOf(fetchSpy)).toHaveLength(2));
  expect(JSON.parse(String(patchesOf(fetchSpy)[1]![1].body)).preferred).toEqual(
    { type: "capability", tool_id: 1 }
  );
  expect(result.current.preferredAction).toBeNull();
});

test("a plugin that is no longer on the agent is off, so its saved action is not sent", () => {
  mockPluginIds = ["plugin-b"];
  const action = {
    type: "action",
    plugin_id: "plugin-a",
    action: "create_issue",
  } as const;
  openSavedChats({
    abc: {
      allowed: null,
      preferred: action,
      internal_search_filters: NO_FILTERS,
    },
  });
  const { result } = renderHook(() => useToolConfiguration());
  expect(result.current.isPluginEnabled("plugin-a")).toBe(false);
  expect(result.current.isPluginEnabled("plugin-b")).toBe(true);
  expect(
    effectiveChatPreference({
      requestedToolId: result.current.preferredToolId,
      requestedAction: result.current.preferredAction,
      agent: mockActiveAgent,
      isPluginEnabled: result.current.isPluginEnabled,
    })
  ).toBeNull();
});

test("a source change is saved at once, so a reload right after keeps it", async () => {
  openSavedChats();
  const fetchSpy = echoSaves();
  const { result, unmount } = renderHook(() => useToolConfiguration());
  act(() => {
    result.current.setFilters((current) => ({
      ...current,
      selectedSources: ["notion"],
    }));
  });
  await act(async () => {
    await Promise.resolve();
  });
  // Sent without waiting, and kept alive across a page unload.
  expect(patchesOf(fetchSpy)).toHaveLength(1);
  const [, init] = patchesOf(fetchSpy)[0]!;
  expect(init.keepalive).toBe(true);
  expect(JSON.parse(String(init.body))).toEqual({
    internal_search_filters: { ...NO_FILTERS, source_type: ["notion"] },
  });
  await waitFor(() =>
    expect(
      useChatSessionStore.getState().sessions.get("abc")?.toolOptionsEdits
    ).toBeUndefined()
  );
  unmount();

  const reloaded = renderHook(() => useToolConfiguration());
  expect(reloaded.result.current.filters.selectedSources).toEqual(["notion"]);
});

test("a choice whose save is running survives a chat switch and a later edit", async () => {
  openSavedChats({ abc: null, other: null });
  let finishFirst: (response: Response) => void = () => {};
  let patchCount = 0;
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockImplementation(async (_url, init) => {
      if (init?.method !== "PATCH") return new Response(JSON.stringify([]));
      patchCount += 1;
      if (patchCount > 1) return new Response(String(init.body));
      return new Promise<Response>((resolve) => {
        finishFirst = resolve;
      });
    });
  const { result, rerender } = renderHook(() => useToolConfiguration());
  act(() => result.current.toggleToolState(2, "disabled"));
  await waitFor(() => expect(patchesOf(fetchSpy)).toHaveLength(1));

  mockChatId = "other";
  rerender();
  mockChatId = "abc";
  rerender();
  expect(result.current.disabledToolIds).toEqual([2]);

  act(() => result.current.toggleToolState(1, "preferred"));
  expect(result.current.disabledToolIds).toEqual([2]);
  expect(result.current.preferredToolId).toBe(1);

  finishFirst(
    new Response(
      JSON.stringify({
        allowed: [{ type: "capability", tool_id: 1 }],
        preferred: null,
        internal_search_filters: null,
      })
    )
  );
  await waitFor(() => expect(patchesOf(fetchSpy)).toHaveLength(2));
  expect(JSON.parse(String(patchesOf(fetchSpy)[1]![1].body))).toEqual({
    allowed: [{ type: "capability", tool_id: 1 }],
    preferred: { type: "capability", tool_id: 1 },
  });
});

test("a chat load that started before a save finished keeps the saved choice", async () => {
  openSavedChats();
  echoSaves();
  const store = useChatSessionStore.getState();
  // A chat load reads the selection before the save below is confirmed.
  const loadStartedAt = store.sessions.get("abc")?.toolOptionsVersion ?? 0;
  const { result } = renderHook(() => useToolConfiguration());
  act(() => result.current.toggleToolState(2, "disabled"));
  await act(async () => {
    await Promise.resolve();
  });
  await act(() => flushToolOptions("abc"));

  act(() =>
    useChatSessionStore
      .getState()
      .initializeSession("abc", staleChatDetail("abc"), loadStartedAt)
  );
  expect(result.current.disabledToolIds).toEqual([2]);
});

test("a chat that stores no selection keeps the tab's choice when it loads again", async () => {
  openSavedChats({ abc: null }, true);
  // The server keeps nothing for a content-free chat and answers null.
  echoSaves(() => null);
  const { result } = renderHook(() => useToolConfiguration());
  act(() => result.current.toggleToolState(2, "disabled"));
  await act(async () => {
    await Promise.resolve();
  });
  await act(() => flushToolOptions("abc"));
  const store = useChatSessionStore.getState();
  const loadStartedAt = store.sessions.get("abc")?.toolOptionsVersion ?? 0;

  act(() =>
    useChatSessionStore
      .getState()
      .initializeSession("abc", staleChatDetail("abc"), loadStartedAt)
  );
  expect(result.current.disabledToolIds).toEqual([2]);
});

test("a flush resolves once the chat's selection is saved", async () => {
  openSavedChats();
  echoSaves();
  const { result } = renderHook(() => useToolConfiguration());
  act(() => result.current.toggleToolState(2, "disabled"));
  await act(async () => {
    await Promise.resolve();
  });
  await act(() => flushToolOptions("abc"));
  expect(
    useChatSessionStore.getState().sessions.get("abc")?.toolOptions
  ).toMatchObject({ allowed: [{ type: "capability", tool_id: 1 }] });
  expect(
    useChatSessionStore.getState().sessions.get("abc")?.toolOptionsEdits
  ).toBeUndefined();
});

test("a tool-options save waits for the save before it", async () => {
  openSavedChats();
  let finishFirst: (response: Response) => void = () => {};
  let patchCount = 0;
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockImplementation(async (_url, init) => {
      if (init?.method !== "PATCH") return new Response(JSON.stringify([]));
      patchCount += 1;
      if (patchCount > 1) return new Response(String(init.body));
      return new Promise<Response>((resolve) => {
        finishFirst = resolve;
      });
    });
  const { result } = renderHook(() => useToolConfiguration());

  act(() => result.current.toggleToolState(2, "disabled"));
  await waitFor(() => expect(patchesOf(fetchSpy)).toHaveLength(1));
  act(() => result.current.toggleToolState(1, "preferred"));
  await new Promise((resolve) => setTimeout(resolve, 500));
  expect(patchesOf(fetchSpy)).toHaveLength(1);

  finishFirst(new Response(JSON.stringify(null)));
  await waitFor(() => expect(patchesOf(fetchSpy)).toHaveLength(2));
  expect(JSON.parse(String(patchesOf(fetchSpy)[1]![1].body))).toMatchObject({
    allowed: [{ type: "capability", tool_id: 1 }],
    preferred: { type: "capability", tool_id: 1 },
  });
});

test("a remounted composer's save waits for the save before it", async () => {
  openSavedChats();
  let finishFirst: (response: Response) => void = () => {};
  let patchCount = 0;
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockImplementation(async (_url, init) => {
      if (init?.method !== "PATCH") return new Response(JSON.stringify([]));
      patchCount += 1;
      if (patchCount > 1) return new Response(String(init.body));
      return new Promise<Response>((resolve) => {
        finishFirst = resolve;
      });
    });
  const first = renderHook(() => useToolConfiguration());
  act(() => first.result.current.toggleToolState(2, "disabled"));
  await waitFor(() => expect(patchesOf(fetchSpy)).toHaveLength(1));
  first.unmount();

  const second = renderHook(() => useToolConfiguration());
  expect(second.result.current.ready).toBe(true);
  act(() => second.result.current.toggleToolState(1, "preferred"));
  await new Promise((resolve) => setTimeout(resolve, 500));
  expect(patchesOf(fetchSpy)).toHaveLength(1);

  finishFirst(new Response(JSON.stringify(null)));
  await waitFor(() => expect(patchesOf(fetchSpy)).toHaveLength(2));
});

test("a failed tool-options save warns the user", async () => {
  openSavedChats();
  jest
    .spyOn(global, "fetch")
    .mockImplementation(async (_url, init) =>
      init?.method === "PATCH"
        ? new Response(null, { status: 500 })
        : new Response(JSON.stringify([]))
    );
  const errorToast = jest.spyOn(toast, "error").mockReturnValue("toast-id");
  jest.spyOn(console, "error").mockImplementation(() => {});
  const { result } = renderHook(() => useToolConfiguration());
  act(() => result.current.toggleToolState(2, "disabled"));
  await waitFor(() =>
    expect(errorToast).toHaveBeenCalledWith("toolsPopover.selectionSaveFailed")
  );
});

test("opening a chat saves nothing until the user changes a tool", async () => {
  openSavedChats();
  const fetchSpy = echoSaves();
  const { result } = renderHook(() => useToolConfiguration());
  expect(result.current.ready).toBe(true);
  await new Promise((resolve) => setTimeout(resolve, 500));
  expect(patchesOf(fetchSpy)).toHaveLength(0);
});

test("a tool change saves nothing until the user is known", async () => {
  openSavedChats();
  mockUser = null;
  const fetchSpy = echoSaves();
  const { result } = renderHook(() => useToolConfiguration());
  act(() => result.current.toggleToolState(2, "disabled"));
  await new Promise((resolve) => setTimeout(resolve, 500));
  expect(patchesOf(fetchSpy)).toHaveLength(0);
});

test("an incognito chat sends its selection and keeps it when the server stores none", async () => {
  openSavedChats({ abc: null }, true);
  const fetchSpy = echoSaves(() => null);
  const { result, unmount } = renderHook(() => useToolConfiguration());
  act(() => result.current.toggleToolState(2, "disabled"));
  await waitFor(() => expect(patchesOf(fetchSpy)).toHaveLength(1));
  await waitFor(() =>
    expect(
      useChatSessionStore.getState().sessions.get("abc")?.toolOptions
    ).toMatchObject({ allowed: [{ type: "capability", tool_id: 1 }] })
  );
  unmount();
  const reopened = renderHook(() => useToolConfiguration());
  expect(reopened.result.current.disabledToolIds).toEqual([2]);
});

describe("useToolConfiguration: plugins of the agent", () => {
  test("a new chat starts with the plugins the user turned off for the agent", () => {
    mockChatId = null;
    mockActiveAgent = AGENT;
    mockPluginIds = ["plugin-a", "plugin-b"];
    mockDisabledPluginIds = ["plugin-b"];
    const { result } = renderHook(() => useToolConfiguration(7));

    expect(result.current.ready).toBe(true);
    expect(result.current.isPluginEnabled("plugin-a")).toBe(true);
    expect(result.current.isPluginEnabled("plugin-b")).toBe(false);
    expect(result.current.allowed).toEqual([
      { type: "capability", tool_id: 1 },
      { type: "capability", tool_id: 2 },
      { type: "plugin", plugin_id: "plugin-a" },
    ]);
  });

  test("an agent preview reads and saves the plugins of the previewed agent", () => {
    mockChatId = null;
    mockActiveAgent = AGENT;
    mockPluginIds = ["plugin-a"];
    const previewId = AGENT.id + 100;
    const { result } = renderHook(() => useToolConfiguration(previewId));

    act(() => result.current.setPluginEnabled(["plugin-a"], false));
    expect(mockSetPluginsDisabled).toHaveBeenCalledWith(
      previewId,
      ["plugin-a"],
      true
    );
    expect(new Set(mockReadAgentIds)).toEqual(new Set([previewId]));
  });

  test("a tool change sends a saved actions list of a plugin back unchanged", async () => {
    mockPluginIds = ["plugin-a", "plugin-b"];
    const saved: ChatToolOptions = {
      allowed: [
        { type: "capability", tool_id: 1 },
        { type: "capability", tool_id: 2 },
        { type: "plugin", plugin_id: "plugin-a", actions: ["listOrders"] },
        { type: "plugin", plugin_id: "plugin-b" },
      ],
      preferred: null,
      internal_search_filters: NO_FILTERS,
    };
    openSavedChats({ abc: saved });
    const fetchSpy = echoSaves((sent) => ({ ...saved, ...sent }));
    const { result } = renderHook(() => useToolConfiguration());

    act(() => result.current.toggleToolState(2, "disabled"));

    await waitFor(() => expect(patchesOf(fetchSpy)).toHaveLength(1));
    const [, init] = patchesOf(fetchSpy)[0]!;
    expect(JSON.parse(String(init.body)).allowed).toEqual([
      { type: "capability", tool_id: 1 },
      { type: "plugin", plugin_id: "plugin-a", actions: ["listOrders"] },
      { type: "plugin", plugin_id: "plugin-b" },
    ]);
  });

  test("a switch in a chat saves the agent choice and the chat's tool options", async () => {
    mockPluginIds = ["plugin-a", "plugin-b"];
    const fetchSpy = echoSaves();
    openSavedChats();
    const { result } = renderHook(() => useToolConfiguration());

    act(() => result.current.setPluginEnabled(["plugin-a"], false));
    expect(mockSetPluginsDisabled).toHaveBeenCalledWith(
      AGENT.id,
      ["plugin-a"],
      true
    );
    await waitFor(() => expect(patchesOf(fetchSpy)).toHaveLength(1));
    const [url, init] = patchesOf(fetchSpy)[0]!;
    expect(url).toBe("/api/chat/chat-session/abc/tool-options");
    expect(JSON.parse(String(init.body)).allowed).toEqual([
      { type: "capability", tool_id: 1 },
      { type: "capability", tool_id: 2 },
      { type: "plugin", plugin_id: "plugin-b" },
    ]);
  });
});
