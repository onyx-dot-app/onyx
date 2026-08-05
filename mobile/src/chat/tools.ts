// Pure tool contract + selection logic. Mirrors the Tier-2 subset of web's ToolSnapshot
// (web/src/lib/tools/interfaces.ts) and the in-code tool ids in
// web/src/app/app/components/tools/constants.ts. No React — jest-unit-testable.
import type { IconFunctionComponent } from "@/icons/types";
import SvgSearch from "@/icons/search";
import SvgGlobe from "@/icons/globe";
import SvgImage from "@/icons/image";
import SvgTerminalSmall from "@/icons/terminal-small";
import SvgLink from "@/icons/link";
import SvgCpu from "@/icons/cpu";
import SvgServer from "@/icons/server";

export interface ToolSnapshot {
  id: number;
  name: string;
  display_name: string;
  description: string;
  // Matches an in-code id below; null for custom (OpenAPI) tools.
  in_code_tool_id: string | null;
  // Set → this is an MCP tool, excluded from the Tier-2 actions list.
  mcp_server_id: number | null;
  // false → the tool is never offered in the chat actions menu.
  chat_selectable: boolean;
}

// In-code tool identifiers (backend `in_code_tool_id`).
export const SEARCH_TOOL_ID = "SearchTool";
export const WEB_SEARCH_TOOL_ID = "WebSearchTool";
export const IMAGE_GENERATION_TOOL_ID = "ImageGenerationTool";
export const PYTHON_TOOL_ID = "PythonTool";
export const OPEN_URL_TOOL_ID = "OpenURLTool";
export const CODING_AGENT_TOOL_ID = "CodingAgentTool";
export const KNOWLEDGE_GRAPH_TOOL_ID = "KnowledgeGraphTool";
// Always hidden from the actions list (it isn't a user-selectable action).
export const FILE_READER_TOOL_ID = "FileReaderTool";

const TOOL_ICONS: Record<string, IconFunctionComponent> = {
  [SEARCH_TOOL_ID]: SvgSearch,
  [WEB_SEARCH_TOOL_ID]: SvgGlobe,
  [IMAGE_GENERATION_TOOL_ID]: SvgImage,
  [PYTHON_TOOL_ID]: SvgTerminalSmall,
  [OPEN_URL_TOOL_ID]: SvgLink,
  [CODING_AGENT_TOOL_ID]: SvgCpu,
  [KNOWLEDGE_GRAPH_TOOL_ID]: SvgServer,
};

// Falls back to the cpu glyph for custom/unknown tools, matching web's getIconForAction catch-all
// (web/src/app/app/services/actionUtils.ts).
export function getIconForToolId(
  inCodeToolId: string | null,
): IconFunctionComponent {
  if (inCodeToolId && inCodeToolId in TOOL_ICONS) {
    return TOOL_ICONS[inCodeToolId];
  }
  return SvgCpu;
}

export function isSearchTool(tool: ToolSnapshot): boolean {
  return tool.in_code_tool_id === SEARCH_TOOL_ID;
}

export function isWebSearchTool(tool: ToolSnapshot): boolean {
  return tool.in_code_tool_id === WEB_SEARCH_TOOL_ID;
}

// Deep research (and the source sub-view) only apply when the agent can search.
export function hasSearchToolsAvailable(tools: ToolSnapshot[]): boolean {
  return tools.some((t) => isSearchTool(t) || isWebSearchTool(t));
}

// The tools shown in the actions menu: selectable, non-MCP, and not the File Reader.
export function displayableTools(tools: ToolSnapshot[]): ToolSnapshot[] {
  return tools.filter(
    (t) =>
      t.chat_selectable &&
      t.mcp_server_id == null &&
      t.in_code_tool_id !== FILE_READER_TOOL_ID,
  );
}

// null when nothing is disabled → backend allows every tool. Otherwise the enabled ids (which may
// be [] if the user disabled all). Never send a bare [] just because no prefs exist.
export function computeAllowedToolIds(
  tools: ToolSnapshot[],
  disabledToolIds: number[],
): number[] | null {
  if (disabledToolIds.length === 0) return null;
  const disabled = new Set(disabledToolIds);
  return tools.map((t) => t.id).filter((id) => !disabled.has(id));
}
