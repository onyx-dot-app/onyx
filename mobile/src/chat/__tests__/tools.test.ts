import { describe, expect, it } from "@jest/globals";

import { buildInternalSearchFilters } from "@/chat/sources";
import {
  computeAllowedEntries,
  displayableTools,
  FILE_READER_TOOL_ID,
  getIconForToolId,
  hasSearchToolsAvailable,
  KNOWLEDGE_GRAPH_TOOL_ID,
  SEARCH_TOOL_ID,
  WEB_SEARCH_TOOL_ID,
  type ToolSnapshot,
} from "@/chat/tools";
import SvgCpu from "@/icons/cpu";
import SvgSearch from "@/icons/search";
import SvgServer from "@/icons/server";

function tool(over: Partial<ToolSnapshot> & { id: number }): ToolSnapshot {
  return {
    id: over.id,
    name: over.name ?? `tool-${over.id}`,
    display_name: over.display_name ?? `Tool ${over.id}`,
    description: over.description ?? "",
    in_code_tool_id: over.in_code_tool_id ?? null,
    mcp_server_id: over.mcp_server_id ?? null,
    chat_selectable: over.chat_selectable ?? true,
  };
}

describe("computeAllowedEntries", () => {
  const tools = [
    tool({ id: 1, in_code_tool_id: SEARCH_TOOL_ID }),
    tool({ id: 2, in_code_tool_id: WEB_SEARCH_TOOL_ID }),
    // An OpenAPI tool: its plugin names it.
    tool({ id: 3 }),
  ];
  const capability = (id: number) => ({ type: "capability", tool_id: id });
  const plugin = (id: string) => ({ type: "plugin", plugin_id: id });

  it("returns null when nothing is off (backend allows all)", () => {
    expect(computeAllowedEntries(tools, [], [], ["p1"])).toBeNull();
  });

  it("keeps every known plugin when a built-in tool is off", () => {
    expect(computeAllowedEntries(tools, [2], [], ["p1", "p2"])).toEqual([
      capability(1),
      plugin("p1"),
      plugin("p2"),
    ]);
  });

  it("leaves out a plugin that is off", () => {
    expect(computeAllowedEntries(tools, [], ["p2"], ["p1", "p2"])).toEqual([
      capability(1),
      capability(2),
      plugin("p1"),
    ]);
  });

  it("returns [] when the user explicitly disables everything", () => {
    expect(computeAllowedEntries(tools, [1, 2], ["p1"], ["p1"])).toEqual([]);
  });
});

describe("hasSearchToolsAvailable", () => {
  it("is true when a search or web-search tool is present", () => {
    expect(
      hasSearchToolsAvailable([
        tool({ id: 1, in_code_tool_id: SEARCH_TOOL_ID }),
      ]),
    ).toBe(true);
    expect(
      hasSearchToolsAvailable([
        tool({ id: 1, in_code_tool_id: WEB_SEARCH_TOOL_ID }),
      ]),
    ).toBe(true);
  });

  it("is false when the agent has no search tools", () => {
    expect(
      hasSearchToolsAvailable([tool({ id: 1, in_code_tool_id: "PythonTool" })]),
    ).toBe(false);
    expect(hasSearchToolsAvailable([])).toBe(false);
  });
});

describe("displayableTools", () => {
  it("drops MCP tools, non-selectable tools, and the File Reader", () => {
    const list = [
      tool({ id: 1, in_code_tool_id: SEARCH_TOOL_ID }),
      tool({ id: 2, mcp_server_id: 9 }),
      tool({ id: 3, chat_selectable: false }),
      tool({ id: 4, in_code_tool_id: FILE_READER_TOOL_ID }),
    ];
    expect(displayableTools(list).map((t) => t.id)).toEqual([1]);
  });
});

describe("getIconForToolId", () => {
  it("maps known in-code tools to their web-parity icons", () => {
    expect(getIconForToolId(SEARCH_TOOL_ID)).toBe(SvgSearch);
    expect(getIconForToolId(KNOWLEDGE_GRAPH_TOOL_ID)).toBe(SvgServer);
  });

  it("falls back to the cpu glyph for custom/unknown tools (matches web)", () => {
    expect(getIconForToolId(null)).toBe(SvgCpu);
    expect(getIconForToolId("SomeCustomTool")).toBe(SvgCpu);
  });
});

describe("buildInternalSearchFilters", () => {
  it("is null when no sources are selected", () => {
    expect(buildInternalSearchFilters([])).toBeNull();
  });

  it("wraps the selected sources in source_type", () => {
    expect(buildInternalSearchFilters(["web", "confluence"])).toEqual({
      source_type: ["web", "confluence"],
    });
  });
});
