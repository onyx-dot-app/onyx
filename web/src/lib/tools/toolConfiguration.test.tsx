import { renderHook, act, waitFor } from "@testing-library/react";
import {
  type SourceMetadata,
  ValidSources,
} from "@/lib/connectors/types/source";
import { useToolConfiguration } from "@/lib/tools/hooks";
import useDeepResearchToggle from "@/hooks/useDeepResearchToggle";
import type { MinimalAgent } from "@/lib/agents/types";
import type { ToolSnapshot } from "@/lib/tools/types";
import type { User } from "@/lib/types";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { toast } from "@opal/layouts";
import {
  selectedSourcesFrom,
  buildFilters,
  toggleSourceSelection,
  normalizeSourceSelection,
} from "@/lib/searchFilters/utils";

const CHAT_KEY = "onyx:tools:chat:abc";

// Mutable so a test can move the composer between chats; the hook re-keys
// from what useAppPosition reports on each render.
let mockChatId = "abc";

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
jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({ user: mockUser }),
}));

beforeEach(() => {
  sessionStorage.clear();
  mockChatId = "abc";
  mockIncognitoEnabled = false;
  mockActiveAgent = undefined;
  mockUser = SIGNED_IN;
});

function source(internalName: ValidSources, uniqueKey: string): SourceMetadata {
  return { internalName, uniqueKey } as SourceMetadata;
}

const NOTION = source(ValidSources.Notion, "notion");
const SLACK = source(ValidSources.Slack, "slack");

describe("useToolConfiguration: stored shapes", () => {
  test("the pre-filters flat shape still reads as the tool map", () => {
    sessionStorage.setItem(
      CHAT_KEY,
      JSON.stringify({ 1: "preferred", 2: "disabled" })
    );
    const { result } = renderHook(() => useToolConfiguration());

    expect(result.current.preferredToolId).toBe(1);
    expect(result.current.disabledToolIds).toEqual([2]);
    expect(result.current.filters.selectedSources).toBeNull();
    expect(result.current.filters.timeRange).toBeNull();
  });

  test.each([false, true])(
    "obsolete forced selections are dropped in stored shape (nested=%s)",
    (nested) => {
      sessionStorage.setItem(
        CHAT_KEY,
        JSON.stringify(
          nested
            ? { tools: { 1: "forced", 2: "disabled" } }
            : { 1: "forced", 2: "disabled" }
        )
      );
      const { result } = renderHook(() => useToolConfiguration());
      expect(result.current.preferredToolId).toBeNull();
      expect(result.current.disabledToolIds).toEqual([2]);
    }
  );

  test("filters ride the snapshot through storage", () => {
    const { result, unmount } = renderHook(() => useToolConfiguration());
    act(() => {
      result.current.setFilters((current) => ({
        ...current,
        selectedSources: ["notion"],
      }));
    });
    unmount();

    const { result: reread } = renderHook(() => useToolConfiguration());
    expect(reread.current.filters.selectedSources).toEqual(["notion"]);
  });
});

describe("useToolConfiguration: chat scoping", () => {
  test("each chat keeps its own configuration", () => {
    const { result, rerender } = renderHook(() => useToolConfiguration());
    act(() => {
      result.current.setFilters((current) => ({
        ...current,
        selectedSources: ["notion"],
      }));
    });
    act(() => result.current.toggleToolState(7, "preferred"));

    // Another chat reads its own (neutral) configuration...
    mockChatId = "other";
    rerender();
    expect(result.current.filters.selectedSources).toBeNull();
    expect(result.current.preferredToolId).toBeNull();

    // ...and edits it without touching the first chat's.
    act(() => {
      result.current.setFilters((current) => ({
        ...current,
        selectedSources: [],
      }));
    });

    mockChatId = "abc";
    rerender();
    expect(result.current.filters.selectedSources).toEqual(["notion"]);
    expect(result.current.preferredToolId).toBe(7);
  });
});

describe("useToolConfiguration: orthogonal axes", () => {
  test("editing sources never touches a preferred pin", () => {
    const { result } = renderHook(() => useToolConfiguration());
    act(() => result.current.toggleToolState(7, "preferred"));
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

    expect(result.current.preferredToolId).toBe(7);
  });

  test("tool state changes never touch the source selection", () => {
    const { result } = renderHook(() => useToolConfiguration());
    act(() => {
      result.current.setFilters((current) => ({
        ...current,
        selectedSources: ["notion"],
      }));
    });
    act(() => result.current.toggleToolState(7, "preferred"));
    act(() => result.current.toggleToolState(7, "preferred"));
    act(() => result.current.toggleToolState(8, "disabled"));

    expect(result.current.filters.selectedSources).toEqual(["notion"]);
  });
});

describe("selectedSourcesFrom: positive-selection semantics", () => {
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

test("tool preference persists through chat handoff and reload", () => {
  const { result, rerender, unmount } = renderHook(() =>
    useToolConfiguration()
  );
  act(() => {
    result.current.setToolState(1, () => "preferred");
    result.current.setToolState(2, () => "disabled");
  });
  act(() => result.current.handOffTo("created"));
  expect(result.current.preferredToolId).toBe(1);
  mockChatId = "created";
  rerender();
  expect(result.current.preferredToolId).toBe(1);
  expect(result.current.disabledToolIds).toEqual([2]);
  unmount();
  const reloaded = renderHook(() => useToolConfiguration());
  expect(reloaded.result.current.preferredToolId).toBe(1);
  act(() => reloaded.result.current.clearPreferredTool());
  expect(reloaded.result.current.preferredToolId).toBeNull();
});

test("Deep Research and a tool preference are mutually exclusive", () => {
  const { result } = renderHook(() => {
    const configuration = useToolConfiguration();
    const research = useDeepResearchToggle({
      chatSessionId: "abc",
      agentId: 1,
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

function openSavedChat(loaded: boolean = true): void {
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
  mockActiveAgent = {
    id: 7,
    name: "Agent",
    description: "",
    tools: [tool(1), tool(2)],
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
  useChatSessionStore.setState({ sessions: new Map(), currentSessionId: null });
  if (loaded) {
    useChatSessionStore.getState().createSession("abc", { incognito: false });
  }
}

const NO_FILTERS = {
  source_type: null,
  document_set: null,
  updated_at_range: null,
  tags: [],
};

test("a tool change in an existing chat saves the chat's tool selection once", async () => {
  openSavedChat();
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockImplementation(async () => new Response(JSON.stringify([])));
  const patches = () =>
    fetchSpy.mock.calls.filter(([, init]) => init?.method === "PATCH");
  try {
    const { result } = renderHook(() => useToolConfiguration());
    await waitFor(() => expect(result.current.ready).toBe(true));

    act(() => result.current.toggleToolState(2, "disabled"));
    act(() => result.current.toggleToolState(1, "preferred"));
    await waitFor(() => expect(patches()).toHaveLength(1));
    const [url, init] = patches()[0]!;
    expect(url).toBe("/api/chat/chat-session/abc/tool-selection");
    expect(JSON.parse(String(init?.body))).toEqual({
      allowed_tool_ids: [1],
      preferred_tool_id: 1,
      internal_search_filters: NO_FILTERS,
    });
  } finally {
    fetchSpy.mockRestore();
  }
});

test("a tool-selection save waits for the save before it", async () => {
  openSavedChat();
  let finishFirst: (response: Response) => void = () => {};
  let patchCount = 0;
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockImplementation(async (_url, init) => {
      if (init?.method !== "PATCH") return new Response(JSON.stringify([]));
      patchCount += 1;
      if (patchCount > 1) return new Response(null, { status: 200 });
      return new Promise<Response>((resolve) => {
        finishFirst = resolve;
      });
    });
  const patches = () =>
    fetchSpy.mock.calls.filter(([, init]) => init?.method === "PATCH");
  try {
    const { result } = renderHook(() => useToolConfiguration());
    await waitFor(() => expect(result.current.ready).toBe(true));

    act(() => result.current.toggleToolState(2, "disabled"));
    await waitFor(() => expect(patches()).toHaveLength(1));
    act(() => result.current.toggleToolState(1, "preferred"));
    await new Promise((resolve) => setTimeout(resolve, 500));
    expect(patches()).toHaveLength(1);

    finishFirst(new Response(null, { status: 200 }));
    await waitFor(() => expect(patches()).toHaveLength(2));
    expect(JSON.parse(String(patches()[1]![1]?.body))).toEqual({
      allowed_tool_ids: [1],
      preferred_tool_id: 1,
      internal_search_filters: NO_FILTERS,
    });
  } finally {
    fetchSpy.mockRestore();
  }
});

test("a failed tool-selection save warns the user", async () => {
  openSavedChat();
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockImplementation(async (_url, init) =>
      init?.method === "PATCH"
        ? new Response(null, { status: 500 })
        : new Response(JSON.stringify([]))
    );
  const errorToast = jest.spyOn(toast, "error").mockReturnValue("toast-id");
  const consoleError = jest
    .spyOn(console, "error")
    .mockImplementation(() => {});
  try {
    const { result } = renderHook(() => useToolConfiguration());
    await waitFor(() => expect(result.current.ready).toBe(true));

    act(() => result.current.toggleToolState(2, "disabled"));
    await waitFor(() =>
      expect(errorToast).toHaveBeenCalledWith(
        "toolsPopover.selectionSaveFailed"
      )
    );
  } finally {
    fetchSpy.mockRestore();
    errorToast.mockRestore();
    consoleError.mockRestore();
  }
});

test("a filter change in an existing chat saves the chat's search filters", async () => {
  openSavedChat();
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockImplementation(async () => new Response(JSON.stringify([])));
  const patches = () =>
    fetchSpy.mock.calls.filter(([, init]) => init?.method === "PATCH");
  try {
    const { result } = renderHook(() => useToolConfiguration());
    await waitFor(() => expect(result.current.ready).toBe(true));

    act(() =>
      result.current.setFilters((current) => ({
        ...current,
        documentSets: ["Handbook"],
      }))
    );
    await waitFor(() => expect(patches()).toHaveLength(1));
    expect(JSON.parse(String(patches()[0]![1]?.body))).toEqual({
      allowed_tool_ids: null,
      preferred_tool_id: null,
      internal_search_filters: { ...NO_FILTERS, document_set: ["Handbook"] },
    });
  } finally {
    fetchSpy.mockRestore();
  }
});

test("a tool change made before the chat details load is saved once they do", async () => {
  openSavedChat(false);
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockImplementation(async () => new Response(JSON.stringify([])));
  const patches = () =>
    fetchSpy.mock.calls.filter(([, init]) => init?.method === "PATCH");
  try {
    const { result } = renderHook(() => useToolConfiguration());
    await waitFor(() => expect(result.current.ready).toBe(true));

    act(() => result.current.toggleToolState(2, "disabled"));
    act(() =>
      useChatSessionStore.getState().createSession("abc", { incognito: false })
    );
    await waitFor(() => expect(patches()).toHaveLength(1));
    expect(JSON.parse(String(patches()[0]![1]?.body))).toEqual({
      allowed_tool_ids: [1],
      preferred_tool_id: null,
      internal_search_filters: NO_FILTERS,
    });
  } finally {
    fetchSpy.mockRestore();
  }
});

test("opening a chat saves nothing until the user changes a tool", async () => {
  openSavedChat();
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockImplementation(async () => new Response(JSON.stringify([])));
  try {
    const { result } = renderHook(() => useToolConfiguration());
    await waitFor(() => expect(result.current.ready).toBe(true));
    await new Promise((resolve) => setTimeout(resolve, 500));
    expect(
      fetchSpy.mock.calls.filter(([, init]) => init?.method === "PATCH")
    ).toHaveLength(0);
  } finally {
    fetchSpy.mockRestore();
  }
});

test("a tool change saves nothing until the user is known", async () => {
  openSavedChat();
  mockUser = null;
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockImplementation(async () => new Response(JSON.stringify([])));
  try {
    const { result } = renderHook(() => useToolConfiguration());
    await waitFor(() => expect(result.current.ready).toBe(true));
    act(() => result.current.toggleToolState(2, "disabled"));
    await new Promise((resolve) => setTimeout(resolve, 500));
    expect(
      fetchSpy.mock.calls.filter(([, init]) => init?.method === "PATCH")
    ).toHaveLength(0);
  } finally {
    fetchSpy.mockRestore();
  }
});
