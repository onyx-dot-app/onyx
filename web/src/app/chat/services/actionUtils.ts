import {
  CpuIcon,
  DatabaseIcon,
  IconProps,
  UsersIcon,
  AppSearchIcon,
  GlobeIcon,
} from "@/components/icons/icons";
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
    tool.in_code_tool_id === "InternetSearchTool" ||
    tool.display_name?.toLowerCase().includes("internet search")
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
): (iconProps: IconProps) => JSX.Element {
  if (isSearchTool(action)) {
    return AppSearchIcon;
  } else if (isWebSearchTool(action)) {
    return GlobeIcon;
  } else if (isImageGenerationTool(action)) {
    return DatabaseIcon;
  } else if (isKnowledgeGraphTool(action)) {
    return DatabaseIcon;
  } else if (isOktaProfileTool(action)) {
    return UsersIcon;
  } else {
    return CpuIcon;
  }
}
