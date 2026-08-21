import { MinimalPersonaSnapshot } from "@/app/admin/agents/interfaces";
import { SEARCH_TOOL_ID } from "@/app/app/components/tools/constants";
import { ToolSnapshot } from "@/lib/tools/interfaces";
import { ValidSources } from "@/lib/types";
import { computeInitialForcedToolIds } from "./computeInitialForcedToolIds";

function makeTool(overrides: Partial<ToolSnapshot> = {}): ToolSnapshot {
  return {
    id: 1,
    name: "InternalSearch",
    display_name: "Internal Search",
    description: "Search the agent's attached knowledge.",
    definition: null,
    custom_headers: [],
    in_code_tool_id: SEARCH_TOOL_ID,
    mcp_server_id: null,
    passthrough_auth: false,
    mcp_required_fields: null,
    ...overrides,
  } as ToolSnapshot;
}

function makeAgent(
  overrides: Partial<MinimalPersonaSnapshot> = {}
): MinimalPersonaSnapshot {
  return {
    id: 42,
    name: "Support Agent",
    description: "Knows the corpus.",
    tools: [],
    starter_messages: null,
    document_sets: [],
    knowledge_sources: [],
    is_public: true,
    is_listed: true,
    display_priority: null,
    is_featured: false,
    builtin_persona: false,
    owner: null,
    ...overrides,
  } as MinimalPersonaSnapshot;
}

describe("computeInitialForcedToolIds", () => {
  it("pre-forces internal search when the agent has knowledge and the tool", () => {
    const tool = makeTool({ id: 7 });
    const agent = makeAgent({
      tools: [tool],
      knowledge_sources: [ValidSources.Confluence],
    });

    expect(computeInitialForcedToolIds(agent, undefined)).toEqual([7]);
  });

  it("returns empty when the agent has no knowledge attached", () => {
    const agent = makeAgent({
      tools: [makeTool()],
      knowledge_sources: [],
    });

    expect(computeInitialForcedToolIds(agent, undefined)).toEqual([]);
  });

  it("returns empty when knowledge_sources is undefined (older payload shape)", () => {
    const agent = makeAgent({
      tools: [makeTool()],
      knowledge_sources: undefined,
    });

    expect(computeInitialForcedToolIds(agent, undefined)).toEqual([]);
  });

  it("returns empty when the agent has knowledge but no internal-search tool", () => {
    const agent = makeAgent({
      tools: [makeTool({ id: 9, in_code_tool_id: "SomeOtherTool" })],
      knowledge_sources: [ValidSources.Confluence],
    });

    expect(computeInitialForcedToolIds(agent, undefined)).toEqual([]);
  });

  it("respects a per-agent disable of the internal-search tool", () => {
    const tool = makeTool({ id: 11 });
    const agent = makeAgent({
      tools: [tool],
      knowledge_sources: [ValidSources.Confluence],
    });

    expect(
      computeInitialForcedToolIds(agent, { disabled_tool_ids: [11] })
    ).toEqual([]);
  });

  it("ignores an MCP-wrapped variant of the search tool", () => {
    const agent = makeAgent({
      tools: [makeTool({ id: 13, mcp_server_id: 99 })],
      knowledge_sources: [ValidSources.Confluence],
    });

    expect(computeInitialForcedToolIds(agent, undefined)).toEqual([]);
  });

  it("pre-forces regardless of how many knowledge sources are listed", () => {
    const tool = makeTool({ id: 5 });
    const agent = makeAgent({
      tools: [tool],
      knowledge_sources: [
        ValidSources.Confluence,
        ValidSources.GoogleDrive,
        ValidSources.Slack,
      ],
    });

    expect(computeInitialForcedToolIds(agent, undefined)).toEqual([5]);
  });
});
