import { beforeEach, describe, expect, it, jest } from "@jest/globals";
import type { Mock } from "jest-mock";
import * as React from "react";
import { act, renderHook, waitFor } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { apiFetch, type ApiFetchInit } from "@/api/client";
import type { MinimalAgent } from "@/chat/agents";
import {
  FILE_READER_TOOL_ID,
  SEARCH_TOOL_ID,
  type ToolSnapshot,
} from "@/chat/tools";
import { useComposerToolsState } from "@/state/ComposerToolsProvider";
import { appStorage } from "@/state/storage";

// `mock`-prefixed so babel-jest allows the hoisted factory to close over it.
let mockDeepResearchAdminEnabled = true;

jest.mock("@/api/client");
jest.mock("@/state/storage");
/*
 * `getState` too, not just the selector: the preferences write re-reads it as it leaves the queue,
 * and a mock without it drops every PATCH into the rollback path.
 */
jest.mock("@/state/session", () => {
  const state = { serverUrl: "https://example.test" };
  const useSession = (selector: (s: typeof state) => unknown) =>
    selector(state);
  useSession.getState = () => state;
  return { useSession };
});
jest.mock("@/hooks/useToast", () => ({ toast: { error: jest.fn() } }));
jest.mock("@/api/settings", () => ({
  useWorkspaceSettings: () => ({
    settings: {
      disable_default_assistant: false,
      user_file_max_upload_size_mb: null,
      deep_research_enabled: mockDeepResearchAdminEnabled,
      vector_db_enabled: true,
    },
  }),
}));

const apiFetchMock = apiFetch as unknown as Mock<
  (path: string, init?: ApiFetchInit) => Promise<unknown>
>;

const searchTool: ToolSnapshot = {
  id: 1,
  name: "SearchTool",
  display_name: "Search",
  description: "",
  in_code_tool_id: SEARCH_TOOL_ID,
  mcp_server_id: null,
  chat_selectable: true,
};

const imageTool: ToolSnapshot = {
  id: 2,
  name: "ImageTool",
  display_name: "Image",
  description: "",
  in_code_tool_id: null,
  mcp_server_id: null,
  chat_selectable: true,
};

// Hidden from the menu but still part of the agent, so it must survive into allowed_tool_ids.
const fileReaderTool: ToolSnapshot = {
  id: 3,
  name: "FileReaderTool",
  display_name: "File Reader",
  description: "",
  in_code_tool_id: FILE_READER_TOOL_ID,
  mcp_server_id: null,
  chat_selectable: true,
};

function agent(tools: ToolSnapshot[]): MinimalAgent {
  return {
    id: 0,
    name: "Agent",
    description: "",
    starter_messages: null,
    uploaded_image_id: null,
    icon_name: null,
    is_public: true,
    is_listed: true,
    is_featured: false,
    builtin_persona: true,
    display_priority: null,
    labels: [],
    tools,
    knowledge_sources: [],
  };
}

/*
 * One client per test, created outside the wrapper: building it inside would hand every render a
 * fresh cache and drop what a rerender is meant to observe.
 */
let client: QueryClient;

function wrapper({ children }: { children: React.ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function renderTools(
  overrides: { agent?: MinimalAgent | null; isProjectWorkflow?: boolean } = {},
) {
  return renderHook(
    () =>
      useComposerToolsState({
        chatSessionId: null,
        agent:
          overrides.agent === undefined ? agent([searchTool]) : overrides.agent,
        isProjectWorkflow: overrides.isProjectWorkflow ?? false,
        projectId: null,
      }),
    { wrapper },
  );
}

/*
 * The preferences record has to remember what was PATCHed: every write is followed by an
 * invalidate, so a fixed GET response would undo each optimistic update.
 */
function mockApi({
  preferences = {},
  connectors = [] as string[],
  federated = [] as string[],
  holdPreferences = false,
  holdPatch = false,
  holdConnectors = false,
}: {
  preferences?: Record<string, { disabled_tool_ids: number[] }>;
  connectors?: string[];
  federated?: string[];
  // Leaves the preferences GET pending so a test can land the connector list first.
  holdPreferences?: boolean;
  // Leaves the PATCH pending so a test can act while a write is still in flight.
  holdPatch?: boolean;
  // Leaves the connector list pending, so a test can act before it resolves.
  holdConnectors?: boolean;
} = {}) {
  const stored: Record<string, { disabled_tool_ids: number[] }> = {
    ...preferences,
  };
  let release = () => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let releasePatchGate = () => {};
  const patchGate = new Promise<void>((resolve) => {
    releasePatchGate = resolve;
  });
  let releaseConnectorGate = () => {};
  const connectorGate = new Promise<void>((resolve) => {
    releaseConnectorGate = resolve;
  });
  apiFetchMock.mockImplementation((path: string, init?: ApiFetchInit) => {
    if (path === "/manage/connector-status") {
      const rows = () =>
        connectors.map((source) => ({
          has_successful_run: true,
          source,
          status: "ACTIVE",
        }));
      return holdConnectors
        ? connectorGate.then(rows)
        : Promise.resolve(rows());
    }
    if (path === "/federated") {
      return Promise.resolve(
        federated.map((source, index) => ({
          id: index,
          source,
          name: source,
        })),
      );
    }
    if (init?.method === "PATCH") {
      const agentId = path.split("/")[3];
      const apply = () => {
        stored[agentId] = init.body as { disabled_tool_ids: number[] };
        return undefined;
      };
      return holdPatch ? patchGate.then(apply) : Promise.resolve(apply());
    }
    if (holdPreferences) return gate.then(() => ({ ...stored }));
    return Promise.resolve({ ...stored });
  });
  return {
    releasePreferences: () => release(),
    releasePatch: () => releasePatchGate(),
    patchSettled: () => patchGate,
    releaseConnectors: () => releaseConnectorGate(),
    stored,
  };
}

function patchCalls(): { agentId: string; disabled: number[] }[] {
  return apiFetchMock.mock.calls
    .filter(
      ([, init]) =>
        (init as { method?: string } | undefined)?.method === "PATCH",
    )
    .map(([path, init]) => ({
      agentId: String(path).split("/")[3],
      disabled: (init as { body: { disabled_tool_ids: number[] } }).body
        .disabled_tool_ids,
    }));
}

describe("useComposerToolsState", () => {
  beforeEach(() => {
    mockDeepResearchAdminEnabled = true;
    apiFetchMock.mockReset();
    mockApi();
    client = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
    });
  });

  it("shows deep research when the admin allows it and the agent can search", () => {
    expect(renderTools().result.current.showDeepResearch).toBe(true);
  });

  it("hides deep research when the admin setting is off", () => {
    mockDeepResearchAdminEnabled = false;
    expect(renderTools().result.current.showDeepResearch).toBe(false);
  });

  it("hides deep research when the agent has no search tool", () => {
    expect(
      renderTools({ agent: agent([]) }).result.current.showDeepResearch,
    ).toBe(false);
  });

  it("hides deep research while the agent is unknown and the pill is off", () => {
    expect(renderTools({ agent: null }).result.current.showDeepResearch).toBe(
      false,
    );
  });

  it("holds the pill through the agent-unknown window after a send", () => {
    const sendAgent = agent([searchTool]);
    const { result, rerender } = renderHook(
      (props: Parameters<typeof useComposerToolsState>[0]) =>
        useComposerToolsState(props),
      {
        wrapper,
        initialProps: {
          chatSessionId: null,
          agent: sendAgent,
          isProjectWorkflow: false,
          projectId: null,
        },
      },
    );
    act(() => result.current.toggleDeepResearch());

    act(() => result.current.notePendingSend(sendAgent));
    rerender({
      chatSessionId: "session-1",
      agent: null,
      isProjectWorkflow: false,
      projectId: null,
    });
    expect(result.current.showDeepResearch).toBe(true);
    expect(result.current.resolveToolOptions().deepResearch).toBe(true);
  });

  it("hides deep research in a project workflow", () => {
    expect(
      renderTools({ isProjectWorkflow: true }).result.current.showDeepResearch,
    ).toBe(false);
  });

  it("sends the toggled flag and leaves the unset fields null", () => {
    const { result } = renderTools();
    expect(result.current.resolveToolOptions()).toEqual({
      deepResearch: false,
      allowedToolIds: null,
      forcedToolId: null,
      internalSearchFilters: null,
    });

    act(() => result.current.toggleDeepResearch());
    expect(result.current.resolveToolOptions().deepResearch).toBe(true);
  });

  it("never sends deep research while the control is hidden", () => {
    const { result } = renderTools({ isProjectWorkflow: true });
    act(() => result.current.toggleDeepResearch());
    expect(result.current.resolveToolOptions().deepResearch).toBe(false);
  });

  it("exposes only the menu-displayable tools as rows", () => {
    const { result } = renderTools({
      agent: agent([searchTool, fileReaderTool]),
    });
    expect(result.current.actionTools.map((tool) => tool.id)).toEqual([1]);
  });

  it("has no rows while the agent is unresolved", () => {
    expect(renderTools({ agent: null }).result.current.actionTools).toEqual([]);
  });

  it("sends the forced tool id once a row is forced", () => {
    const { result } = renderTools({ agent: agent([searchTool, imageTool]) });
    act(() => result.current.toggleForcedTool(2));
    expect(result.current.resolveToolOptions().forcedToolId).toBe(2);
  });

  it("refuses to send a forced id the agent doesn't expose", () => {
    const { result } = renderTools({ agent: agent([searchTool]) });
    act(() => result.current.toggleForcedTool(99));
    expect(result.current.resolveToolOptions().forcedToolId).toBeNull();
  });

  it("computes allowed ids from every agent tool, not just the visible rows", async () => {
    mockApi({ preferences: { "0": { disabled_tool_ids: [2] } } });
    const { result } = renderTools({
      agent: agent([searchTool, imageTool, fileReaderTool]),
    });

    await waitFor(() => expect(result.current.disabledToolIds).toEqual([2]));
    expect(result.current.resolveToolOptions().allowedToolIds).toEqual([1, 3]);
  });

  it("releases the force when the forced tool is disabled", async () => {
    const { result } = renderTools({ agent: agent([searchTool, imageTool]) });
    act(() => result.current.toggleForcedTool(2));
    expect(result.current.forcedToolId).toBe(2);

    await act(async () => {
      result.current.toggleToolEnabled(2);
    });
    expect(result.current.forcedToolId).toBeNull();
  });

  it("keeps the force when a different tool is disabled", async () => {
    const { result } = renderTools({ agent: agent([searchTool, imageTool]) });
    act(() => result.current.toggleForcedTool(2));

    await act(async () => {
      result.current.toggleToolEnabled(1);
    });
    expect(result.current.forcedToolId).toBe(2);
  });

  it("keeps the menu rows while the agent is momentarily unknown", async () => {
    const sendAgent = agent([searchTool, imageTool]);
    const { result, rerender } = renderHook(
      (props: Parameters<typeof useComposerToolsState>[0]) =>
        useComposerToolsState(props),
      {
        wrapper,
        initialProps: {
          chatSessionId: null,
          agent: sendAgent,
          isProjectWorkflow: false,
          projectId: null,
        },
      },
    );
    expect(result.current.actionTools).toHaveLength(2);

    act(() => result.current.notePendingSend(sendAgent));
    rerender({
      chatSessionId: "session-1",
      agent: null,
      isProjectWorkflow: false,
      projectId: null,
    });
    expect(result.current.actionTools).toHaveLength(2);
  });

  it("keeps the disabled set while the agent is momentarily unknown", async () => {
    mockApi({ preferences: { "0": { disabled_tool_ids: [2] } } });
    const sendAgent = agent([searchTool, imageTool]);
    const { result, rerender } = renderHook(
      (props: Parameters<typeof useComposerToolsState>[0]) =>
        useComposerToolsState(props),
      {
        wrapper,
        initialProps: {
          chatSessionId: null,
          agent: sendAgent,
          isProjectWorkflow: false,
          projectId: null,
        },
      },
    );
    await waitFor(() => expect(result.current.disabledToolIds).toEqual([2]));

    act(() => result.current.notePendingSend(sendAgent));
    rerender({
      chatSessionId: "session-1",
      agent: null,
      isProjectWorkflow: false,
      projectId: null,
    });
    expect(result.current.disabledToolIds).toEqual([2]);
    expect(result.current.resolveToolOptions().allowedToolIds).toEqual([1]);
  });

  it("records the agent the send used, not one picked while the create was in flight", async () => {
    const sentWith = agent([searchTool, imageTool]);
    const switchedTo: MinimalAgent = { ...agent([searchTool]), id: 12 };
    const { result, rerender } = renderHook(
      (props: Parameters<typeof useComposerToolsState>[0]) =>
        useComposerToolsState(props),
      {
        wrapper,
        initialProps: {
          chatSessionId: null,
          agent: sentWith,
          isProjectWorkflow: false,
          projectId: null,
        },
      },
    );

    act(() => result.current.notePendingSend(sentWith));
    rerender({
      chatSessionId: null,
      agent: switchedTo,
      isProjectWorkflow: false,
      projectId: null,
    });

    rerender({
      chatSessionId: "session-1",
      agent: null,
      isProjectWorkflow: false,
      projectId: null,
    });
    expect(result.current.actionTools.map((tool) => tool.id)).toEqual([1, 2]);
  });

  it("does not carry the composer's agent into an existing chat opened from the landing", async () => {
    const sendAgent = agent([searchTool, imageTool]);
    const { result, rerender } = renderHook(
      (props: Parameters<typeof useComposerToolsState>[0]) =>
        useComposerToolsState(props),
      {
        wrapper,
        initialProps: {
          chatSessionId: null,
          agent: sendAgent,
          isProjectWorkflow: false,
          projectId: null,
        },
      },
    );
    expect(result.current.actionTools).toHaveLength(2);

    /*
     * No notePendingSend: the user tapped an existing chat rather than sending. The landing's
     * agent says nothing about that conversation.
     */
    rerender({
      chatSessionId: "session-9",
      agent: null,
      isProjectWorkflow: false,
      projectId: null,
    });

    expect(result.current.actionTools).toEqual([]);
    expect(result.current.resolveToolOptions().forcedToolId).toBeNull();
  });

  it("refuses to describe a different conversation with the previous one's agent", async () => {
    mockApi({ preferences: { "0": { disabled_tool_ids: [2] } } });
    const { result, rerender } = renderHook(
      (props: Parameters<typeof useComposerToolsState>[0]) =>
        useComposerToolsState(props),
      {
        wrapper,
        initialProps: {
          chatSessionId: "session-1",
          agent: agent([searchTool, imageTool]),
          isProjectWorkflow: false,
          projectId: null,
        },
      },
    );
    await waitFor(() => expect(result.current.actionTools).toHaveLength(2));
    act(() => result.current.toggleForcedTool(2));

    rerender({
      chatSessionId: "session-2",
      agent: null,
      isProjectWorkflow: false,
      projectId: null,
    });

    expect(result.current.actionTools).toEqual([]);
    expect(result.current.resolveToolOptions()).toEqual({
      deepResearch: false,
      allowedToolIds: null,
      forcedToolId: null,
      internalSearchFilters: null,
    });
  });

  it("still sends the force and the allowlist while the agent is momentarily unknown", async () => {
    mockApi({ preferences: { "0": { disabled_tool_ids: [2] } } });
    const sendAgent = agent([searchTool, imageTool, fileReaderTool]);
    const { result, rerender } = renderHook(
      (props: Parameters<typeof useComposerToolsState>[0]) =>
        useComposerToolsState(props),
      {
        wrapper,
        initialProps: {
          chatSessionId: null,
          agent: sendAgent,
          isProjectWorkflow: false,
          projectId: null,
        },
      },
    );
    await waitFor(() => expect(result.current.disabledToolIds).toEqual([2]));
    act(() => result.current.toggleForcedTool(1));

    act(() => result.current.notePendingSend(sendAgent));
    rerender({
      chatSessionId: "session-1",
      agent: null,
      isProjectWorkflow: false,
      projectId: null,
    });

    expect(result.current.resolveToolOptions().forcedToolId).toBe(1);
    expect(result.current.resolveToolOptions().allowedToolIds).toEqual([1, 3]);
  });

  it("never sends a forced id that is also disabled", async () => {
    mockApi({ preferences: { "0": { disabled_tool_ids: [2] } } });
    const { result } = renderTools({ agent: agent([searchTool, imageTool]) });
    await waitFor(() => expect(result.current.disabledToolIds).toEqual([2]));

    act(() => result.current.toggleForcedTool(2));
    expect(result.current.resolveToolOptions().forcedToolId).toBeNull();
  });
});

describe("useComposerToolsState — sources", () => {
  beforeEach(() => {
    mockDeepResearchAdminEnabled = true;
    apiFetchMock.mockReset();
    mockApi({ connectors: ["notion", "web"] });
    appStorage.clearAll();
    client = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
    });
  });

  async function renderWithSources(
    overrides: Parameters<typeof renderTools>[0] = {},
  ) {
    const view = renderTools(overrides);
    await waitFor(() =>
      expect(view.result.current.sourceOptions.length).toBeGreaterThan(0),
    );
    return view;
  }

  it("offers the workspace's connectors to the default agent", async () => {
    const { result } = await renderWithSources();
    expect(result.current.sourceOptions).toEqual(["notion", "web"]);
    expect(result.current.enabledSourceCount).toBe(2);
    expect(result.current.sourceToolId).toBe(1);
  });

  it("offers a scoped agent only what it declares", async () => {
    const scoped: MinimalAgent = {
      ...agent([searchTool]),
      id: 7,
      knowledge_sources: ["jira"],
    };
    const { result } = await renderWithSources({ agent: scoped });
    expect(result.current.sourceOptions).toEqual(["jira"]);
  });

  it("treats a scoped agent that declares nothing as reaching everything", async () => {
    const scoped: MinimalAgent = { ...agent([searchTool]), id: 7 };
    const { result } = await renderWithSources({ agent: scoped });
    expect(result.current.sourceOptions).toEqual(["notion", "web"]);
  });

  it("sends the picked sources as the search filter", async () => {
    const { result } = await renderWithSources();
    expect(result.current.resolveToolOptions().internalSearchFilters).toEqual({
      source_type: ["notion", "web"],
    });

    act(() => result.current.toggleSource("notion"));
    expect(result.current.resolveToolOptions().internalSearchFilters).toEqual({
      source_type: ["web"],
    });
  });

  it("leaves the source layer out of a project chat", async () => {
    const { result } = renderTools({ isProjectWorkflow: true });
    await waitFor(() => expect(result.current.actionTools).toHaveLength(1));

    expect(result.current.sourceOptions).toEqual([]);
    expect(result.current.sourceToolId).toBeNull();
    expect(
      result.current.resolveToolOptions().internalSearchFilters,
    ).toBeNull();
  });

  it("pins search when a source is switched on", async () => {
    const { result } = await renderWithSources();
    // Off then on: picking a source is a statement about search, so it pins it.
    act(() => result.current.toggleSource("notion"));
    expect(result.current.forcedToolId).toBeNull();

    act(() => result.current.toggleSource("notion"));
    expect(result.current.forcedToolId).toBe(1);
  });

  it("releases the pin only when the last source goes", async () => {
    const { result } = await renderWithSources();
    act(() => result.current.toggleSource("notion"));
    act(() => result.current.toggleSource("notion"));
    expect(result.current.forcedToolId).toBe(1);

    act(() => result.current.toggleSource("notion"));
    expect(result.current.forcedToolId).toBe(1);

    act(() => result.current.toggleSource("web"));
    expect(result.current.forcedToolId).toBeNull();
  });

  it("switches search off with the last source, exactly once", async () => {
    const { result } = await renderWithSources();

    await act(async () => {
      result.current.toggleSource("notion");
    });
    await act(async () => {
      result.current.toggleSource("web");
    });

    await waitFor(() => expect(result.current.disabledToolIds).toEqual([1]));
    /*
     * The handler and the effect both saw the same stale "still enabled"; two writes cancel out
     * and leave search on.
     */
    expect(patchCalls()).toEqual([{ agentId: "0", disabled: [1] }]);
  });

  it("switches search back on with the first source", async () => {
    const { result } = await renderWithSources();
    await act(async () => {
      result.current.disableAllSources();
    });
    await waitFor(() => expect(result.current.disabledToolIds).toEqual([1]));

    await act(async () => {
      result.current.toggleSource("web");
    });
    await waitFor(() => expect(result.current.disabledToolIds).toEqual([]));
    expect(result.current.resolveToolOptions().allowedToolIds).toBeNull();
  });

  it("restores the sources search was switched off with", async () => {
    const { result } = await renderWithSources();
    act(() => result.current.toggleSource("notion"));
    expect(result.current.enabledSourceCount).toBe(1);

    await act(async () => {
      result.current.toggleToolEnabled(1);
    });
    expect(result.current.enabledSourceCount).toBe(0);
    await waitFor(() => expect(result.current.disabledToolIds).toEqual([1]));

    await act(async () => {
      result.current.toggleToolEnabled(1);
    });
    expect(result.current.enabledSourceCount).toBe(1);
    expect(result.current.isSourceEnabled("web")).toBe(true);
  });

  it("offers federated connectors under the name of their indexed twin", async () => {
    /*
     * Never appears among the cc-pairs, so leaving it out of source_type switches federated
     * retrieval off entirely.
     */
    mockApi({ connectors: ["confluence"], federated: ["federated_slack"] });
    const { result } = renderTools();

    await waitFor(() =>
      expect(result.current.sourceOptions).toEqual(["confluence", "slack"]),
    );
    expect(result.current.resolveToolOptions().internalSearchFilters).toEqual({
      source_type: ["confluence", "slack"],
    });
  });

  it("adopts a search switched off elsewhere by clearing the sources", async () => {
    /*
     * The off state is a deliberate, server-persisted choice; the sources it meets are only the
     * picker's "everything" default.
     */
    mockApi({
      preferences: { "0": { disabled_tool_ids: [1] } },
      connectors: ["notion", "web"],
    });
    const { result } = await renderWithSources();

    await waitFor(() => expect(result.current.enabledSourceCount).toBe(0));
    expect(result.current.disabledToolIds).toEqual([1]);
    expect(patchCalls()).toEqual([]);
  });

  it("does not invert the search state when the connector list beats the preferences", async () => {
    /*
     * Both queries are cold on every launch (neither persists), so either can win. Acting on the
     * pre-load "nothing disabled" default asks to switch off a tool the record already has off —
     * and lands as switching it back on.
     */
    appStorage.set(
      "onyx.chat.source_preferences.https://example.test",
      JSON.stringify({ sourcePreferences: { notion: false, web: false } }),
    );
    const api = mockApi({
      preferences: { "0": { disabled_tool_ids: [1] } },
      connectors: ["notion", "web"],
      holdPreferences: true,
    });
    const { result } = renderTools();
    await waitFor(() =>
      expect(result.current.sourceOptions).toEqual(["notion", "web"]),
    );
    expect(result.current.enabledSourceCount).toBe(0);

    await act(async () => {
      api.releasePreferences();
    });

    await waitFor(() => expect(result.current.disabledToolIds).toEqual([1]));
    expect(patchCalls()).toEqual([]);
  });

  it("pins and releases search from the bulk source actions", async () => {
    const { result } = await renderWithSources();

    act(() => result.current.enableAllSources());
    expect(result.current.forcedToolId).toBe(1);

    act(() => result.current.disableAllSources());
    expect(result.current.forcedToolId).toBeNull();
  });

  it("keeps search pinned while a second source is switched on", async () => {
    /*
     * A toggle would read "already forced" and release it, so widening the source set would
     * un-pin search — the opposite of what picking a source means.
     */
    const { result } = await renderWithSources();
    act(() => result.current.toggleSource("notion"));
    act(() => result.current.toggleSource("notion"));
    expect(result.current.forcedToolId).toBe(1);

    act(() => result.current.toggleSource("web"));
    act(() => result.current.toggleSource("web"));
    expect(result.current.forcedToolId).toBe(1);
  });

  it("keeps a Search switched off before the connector list arrived", async () => {
    const api = mockApi({
      connectors: ["notion", "web"],
      holdPreferences: true,
    });
    const { result } = renderTools();
    await waitFor(() => expect(result.current.actionTools).toHaveLength(1));

    // The menu is live while connector-status is still in flight, so the row is tappable here.
    await act(async () => {
      result.current.toggleToolEnabled(1);
      api.releasePreferences();
    });

    await waitFor(() => expect(result.current.disabledToolIds).toEqual([1]));
    /*
     * Sources initialize to "all" a beat later; re-enabling search off that default would
     * silently revert what the user just did.
     */
    await waitFor(() =>
      expect(result.current.sourceOptions).toEqual(["notion", "web"]),
    );
    expect(result.current.disabledToolIds).toEqual([1]);
    expect(result.current.enabledSourceCount).toBe(0);
  });

  it("enables everything when search is switched on with nothing parked", async () => {
    const { result } = await renderWithSources();
    await act(async () => {
      result.current.disableAllSources();
    });
    await waitFor(() => expect(result.current.disabledToolIds).toEqual([1]));

    await act(async () => {
      result.current.toggleToolEnabled(1);
    });
    expect(result.current.enabledSourceCount).toBe(2);
  });

  it("reports a connector list that comes back the wrong shape, without taking the composer down", async () => {
    const warnSpy = jest.spyOn(console, "warn").mockImplementation(() => {});
    // What a proxy error page or an auth redirect answers with: 200, but not the expected list.
    apiFetchMock.mockImplementation((path: string) => {
      if (path === "/manage/connector-status") {
        return Promise.resolve({ detail: "Not authenticated" });
      }
      if (path === "/federated") return Promise.resolve([]);
      return Promise.resolve({});
    });

    const { result } = renderTools();
    await waitFor(() => expect(result.current.actionTools).toHaveLength(1));
    await waitFor(() =>
      expect(warnSpy).toHaveBeenCalledWith(
        expect.stringContaining("/manage/connector-status"),
      ),
    );

    expect(result.current.sourceOptions).toEqual([]);
    // The body names the workspace's connectors, so only its shape may reach the log.
    expect(warnSpy).not.toHaveBeenCalledWith(
      expect.stringContaining("Not authenticated"),
    );

    warnSpy.mockRestore();
  });
  it("says nothing while the connector list is still in flight", async () => {
    // Every launch passes through `undefined`; warning there would fire on each one.
    const warnSpy = jest.spyOn(console, "warn").mockImplementation(() => {});
    mockApi({ connectors: ["notion"], holdConnectors: true });

    const { result } = renderTools();
    await waitFor(() => expect(result.current.actionTools).toHaveLength(1));

    expect(warnSpy).not.toHaveBeenCalled();

    warnSpy.mockRestore();
  });

  it("reconciles an agent switched to while the previous agent's write is in flight", async () => {
    /*
     * The write gate is a ref, and clearing a ref re-renders nothing — so blocking on it for every
     * agent would leave the one switched into unreconciled until some unrelated render, sending
     * source filters that disagree with the tools the same turn allows.
     */
    const api = mockApi({
      preferences: {
        "0": { disabled_tool_ids: [1] },
        "12": { disabled_tool_ids: [1] },
      },
      connectors: ["notion", "web"],
      holdPatch: true,
    });
    const { result, rerender } = renderHook(
      (props: Parameters<typeof useComposerToolsState>[0]) =>
        useComposerToolsState(props),
      {
        wrapper,
        initialProps: {
          chatSessionId: "session-1",
          agent: agent([searchTool]),
          isProjectWorkflow: false,
          projectId: null,
        },
      },
    );
    // Both queries have to land before the count means anything — it reads 0 while empty.
    await waitFor(() =>
      expect(result.current.sourceOptions).toEqual(["notion", "web"]),
    );
    await waitFor(() => expect(result.current.disabledToolIds).toEqual([1]));
    await waitFor(() => expect(result.current.enabledSourceCount).toBe(0));

    // Switching search back on restores the sources and starts a write the gate holds open.
    await act(async () => {
      result.current.toggleToolEnabled(1);
    });
    expect(result.current.enabledSourceCount).toBe(2);

    const other: MinimalAgent = { ...agent([searchTool]), id: 12 };
    rerender({
      chatSessionId: "session-1",
      agent: other,
      isProjectWorkflow: false,
      projectId: null,
    });
    await act(async () => {
      api.releasePatch();
      await api.patchSettled();
    });

    // Agent 12 also has search off, so its first reconcile has to clear the carried-over sources.
    await waitFor(() => expect(result.current.enabledSourceCount).toBe(0));
    expect(
      result.current.resolveToolOptions().internalSearchFilters,
    ).toBeNull();
  });
});
