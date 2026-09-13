import type { IconProps } from "@opal/types";
import {
  SvgCpu,
  SvgGlobe,
  SvgImage,
  SvgLink,
  SvgSearch,
  SvgTerminal,
} from "@opal/icons";

// Tool names as referenced by tool results / tool calls
export const SEARCH_TOOL_NAME = "run_search";
export const INTERNET_SEARCH_TOOL_NAME = "run_internet_search";
export const IMAGE_GENERATION_TOOL_NAME = "run_image_generation";
export const PYTHON_TOOL_NAME = "run_python";
export const OPEN_URL_TOOL_NAME = "open_url";

// In-code tool IDs that also correspond to the tool's name when associated with a persona
export const SEARCH_TOOL_ID = "SearchTool";
export const IMAGE_GENERATION_TOOL_ID = "ImageGenerationTool";
export const WEB_SEARCH_TOOL_ID = "WebSearchTool";
export const PYTHON_TOOL_ID = "PythonTool";
export const OPEN_URL_TOOL_ID = "OpenURLTool";
export const FILE_READER_TOOL_ID = "FileReaderTool";
export const CODING_AGENT_TOOL_ID = "CodingAgentTool";
export const KNOWLEDGE_GRAPH_TOOL_ID = "KnowledgeGraphTool";
export const MEMORY_TOOL_ID = "MemoryTool";

// Icon mappings for system tools
export const SYSTEM_TOOL_ICONS: Record<
  string,
  React.FunctionComponent<IconProps>
> = {
  [SEARCH_TOOL_ID]: SvgSearch,
  [WEB_SEARCH_TOOL_ID]: SvgGlobe,
  [IMAGE_GENERATION_TOOL_ID]: SvgImage,
  [PYTHON_TOOL_ID]: SvgTerminal,
  [OPEN_URL_TOOL_ID]: SvgLink,
  [CODING_AGENT_TOOL_ID]: SvgCpu,
};

import { ADMIN_ROUTES } from "@/lib/admin-routes";

/**
 * Where an admin goes to configure a built-in tool.
 */
export const ADMIN_CONFIG_LINKS: Record<
  string,
  { href: string; tooltip: string }
> = {
  [IMAGE_GENERATION_TOOL_ID]: {
    href: ADMIN_ROUTES.IMAGE_GENERATION.path,
    tooltip: "Configure Image Generation",
  },
  [WEB_SEARCH_TOOL_ID]: {
    href: ADMIN_ROUTES.WEB_SEARCH.path,
    tooltip: "Configure Web Search",
  },
  [PYTHON_TOOL_ID]: {
    href: ADMIN_ROUTES.CODE_INTERPRETER.path,
    tooltip: "Configure Code Interpreter",
  },
};

/** Where an admin goes for a tool that is neither built-in nor from MCP. */
export const OPENAPI_ADMIN_CONFIG = {
  href: ADMIN_ROUTES.OPENAPI_ACTIONS.path,
  tooltip: "Manage OpenAPI Actions",
};
