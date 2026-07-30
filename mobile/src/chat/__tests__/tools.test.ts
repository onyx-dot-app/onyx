import { describe, expect, it } from "@jest/globals";

import { buildInternalSearchFilters } from "@/chat/sources";
import {
  computeAllowedToolIds,
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

describe("computeAllowedToolIds", () => {
  const tools = [tool({ id: 1 }), tool({ id: 2 }), tool({ id: 3 })];

  it("returns null when nothing is disabled (backend allows all)", () => {
    expect(computeAllowedToolIds(tools, [])).toBeNull();
  });

  it("returns the enabled ids when some tools are disabled", () => {
    expect(computeAllowedToolIds(tools, [2])).toEqual([1, 3]);
  });

  it("returns [] when the user explicitly disables every tool", () => {
    expect(computeAllowedToolIds(tools, [1, 2, 3])).toEqual([]);
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
