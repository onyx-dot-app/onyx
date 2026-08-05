import { beforeEach, describe, expect, it, jest } from "@jest/globals";
import { act, renderHook } from "@testing-library/react-native";

import type { MinimalAgent } from "@/chat/agents";
import { SEARCH_TOOL_ID, type ToolSnapshot } from "@/chat/tools";
import { useComposerToolsState } from "@/state/ComposerToolsProvider";

// `mock`-prefixed so babel-jest allows the hoisted factory to close over it.
let mockDeepResearchAdminEnabled = true;

jest.mock("@/api/settings", () => ({
  useWorkspaceSettings: () => ({
    settings: {
      disable_default_assistant: false,
      user_file_max_upload_size_mb: null,
      deep_research_enabled: mockDeepResearchAdminEnabled,
    },
  }),
}));

const searchTool: ToolSnapshot = {
  id: 1,
  name: "SearchTool",
  display_name: "Search",
  description: "",
  in_code_tool_id: SEARCH_TOOL_ID,
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

function renderTools(
  overrides: { agent?: MinimalAgent | null; isProjectWorkflow?: boolean } = {},
) {
  return renderHook(() =>
    useComposerToolsState({
      chatSessionId: null,
      agent:
        overrides.agent === undefined ? agent([searchTool]) : overrides.agent,
      isProjectWorkflow: overrides.isProjectWorkflow ?? false,
    }),
  );
}

describe("useComposerToolsState", () => {
  beforeEach(() => {
    mockDeepResearchAdminEnabled = true;
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
    const { result, rerender } = renderHook(
      (props: Parameters<typeof useComposerToolsState>[0]) =>
        useComposerToolsState(props),
      {
        initialProps: {
          chatSessionId: null,
          agent: agent([searchTool]),
          isProjectWorkflow: false,
        },
      },
    );
    act(() => result.current.toggleDeepResearch());

    // Re-gating here would withdraw the control the user just used and drop it from the request.
    rerender({
      chatSessionId: "session-1",
      agent: null,
      isProjectWorkflow: false,
    });
    expect(result.current.showDeepResearch).toBe(true);
    expect(result.current.resolveToolOptions().deepResearch).toBe(true);
  });

  it("hides deep research in a project workflow", () => {
    expect(
      renderTools({ isProjectWorkflow: true }).result.current.showDeepResearch,
    ).toBe(false);
  });

  it("sends the toggled flag and leaves the later fields unset", () => {
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
});
