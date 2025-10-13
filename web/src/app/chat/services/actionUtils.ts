import { SvgProps } from "@/icons";
import SvgCpu from "@/icons/cpu";
import SvgGlobe from "@/icons/globe";
import SvgImage from "@/icons/image";
import SvgSearch from "@/icons/search";
import SvgServer from "@/icons/server";
import SvgUser from "@/icons/user";
import { ToolSnapshot } from "@/lib/tools/interfaces";

// Helper functions to identify specific tools
const isSearchTool = (tool: ToolSnapshot): boolean => {
  return (
    tool.in_code_tool_id === "SearchTool" ||
    tool.name === "run_search" ||
    tool.display_name?.toLowerCase().includes("search tool")
  );
};

const isWebSearchTool = (tool: ToolSnapshot): boolean => {
  return (
    tool.in_code_tool_id === "WebSearchTool" ||
    tool.display_name?.toLowerCase().includes("web_search")
  );
};

const isImageGenerationTool = (tool: ToolSnapshot): boolean => {
  return (
    tool.in_code_tool_id === "ImageGenerationTool" ||
    tool.display_name?.toLowerCase().includes("image generation")
  );
};

const isKnowledgeGraphTool = (tool: ToolSnapshot): boolean => {
  return (
    tool.in_code_tool_id === "KnowledgeGraphTool" ||
    tool.display_name?.toLowerCase().includes("knowledge graph")
  );
};

const isOktaProfileTool = (tool: ToolSnapshot): boolean => {
  return (
    tool.in_code_tool_id === "OktaProfileTool" ||
    tool.display_name?.toLowerCase().includes("okta profile")
  );
};

export function getIconForAction(
  action: ToolSnapshot
): (props: SvgProps) => JSX.Element {
  if (isSearchTool(action)) return SvgSearch;
  if (isWebSearchTool(action)) return SvgGlobe;
  if (isImageGenerationTool(action)) return SvgImage;
  if (isKnowledgeGraphTool(action)) return SvgServer;
  if (isOktaProfileTool(action)) return SvgUser;
  return SvgCpu;
}

// Check if the assistant has either search tool or web search tool available
export function hasSearchToolsAvailable(tools: ToolSnapshot[]): boolean {
  return tools.some((tool) => isSearchTool(tool) || isWebSearchTool(tool));
}
