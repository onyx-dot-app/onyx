import { renderHook } from "@testing-library/react";
import { ValidSources } from "@/lib/types";
import { DEFAULT_AGENT_ID } from "@/lib/constants";
import { SEARCH_TOOL_ID } from "@/lib/tools/constants";
import type { MinimalAgent } from "@/lib/agents/types";
import type { ToolSnapshot } from "@/lib/tools/types";
import { useAgentAvailableSources } from "@/lib/searchFilters/hooks";
import { buildFilters } from "@/lib/searchFilters/utils";
import { getConfiguredSources } from "@/lib/sources";

const WORKSPACE_SOURCES = [ValidSources.Notion, ValidSources.Slack];

jest.mock("@/lib/connectors/hooks", () => ({
  useAvailableSources: () => ({
    availableSources: [ValidSources.Notion, ValidSources.Slack],
    isLoading: false,
    error: null,
  }),
}));

function agent(overrides: Partial<MinimalAgent>): MinimalAgent {
  return {
    id: 7,
    name: "test-agent",
    description: "",
    tools: [],
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
    ...overrides,
  };
}

const searchTool = { in_code_tool_id: SEARCH_TOOL_ID } as ToolSnapshot;

function sources(agentUnderTest: MinimalAgent | undefined): string[] {
  const { result } = renderHook(() => useAgentAvailableSources(agentUnderTest));
  return [...result.current].sort();
}

describe("useAgentAvailableSources", () => {
  test("the default agent reaches every workspace source", () => {
    expect(sources(agent({ id: DEFAULT_AGENT_ID }))).toEqual(
      [...WORKSPACE_SOURCES].sort()
    );
  });

  test("an agent is bounded by its knowledge sources", () => {
    expect(
      sources(agent({ knowledge_sources: [ValidSources.Notion] }))
    ).toEqual(["notion"]);
  });

  test("knowledge sources can name what no connector provides", () => {
    // user_file is agent-only: it is never in the workspace connector list.
    expect(
      sources(
        agent({
          knowledge_sources: [ValidSources.Notion, ValidSources.UserFile],
        })
      )
    ).toEqual(["notion", "user_file"]);
  });

  test("a search tool with no declared knowledge reaches everything", () => {
    expect(sources(agent({ tools: [searchTool] }))).toEqual(
      [...WORKSPACE_SOURCES].sort()
    );
  });
});

describe("useAgentAvailableSources + buildFilters", () => {
  test("an agent-only source turned off is still sent as a filter", () => {
    // Measured against the workspace list instead, {notion} would look like
    // "everything selected" and the disabled user_file would be searched.
    const universe = getConfiguredSources(
      sources(
        agent({
          knowledge_sources: [ValidSources.Notion, ValidSources.UserFile],
        })
      ) as ValidSources[]
    );
    const selected = universe.filter(
      (source) => source.internalName !== ValidSources.UserFile
    );

    const filters = buildFilters(selected, universe, [], null, []);
    expect(filters.source_type).toEqual(["notion"]);
  });

  test("the full agent selection is not a filter", () => {
    const universe = getConfiguredSources(
      sources(
        agent({
          knowledge_sources: [ValidSources.Notion, ValidSources.UserFile],
        })
      ) as ValidSources[]
    );

    expect(
      buildFilters(universe, universe, [], null, []).source_type
    ).toBeNull();
  });
});
