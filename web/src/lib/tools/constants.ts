import {
  CODING_AGENT_TOOL_ID,
  IMAGE_GENERATION_TOOL_ID,
  PYTHON_TOOL_ID,
  SEARCH_TOOL_ID,
  WEB_SEARCH_TOOL_ID,
} from "@/app/app/components/tools/constants";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

/** What each built-in tool does, shown as the row's tooltip. */
export const TOOL_DESCRIPTIONS: Record<string, string> = {
  [SEARCH_TOOL_ID]: "Search through connected knowledge to inform the answer.",
  [IMAGE_GENERATION_TOOL_ID]: "Generate images based on a prompt.",
  [WEB_SEARCH_TOOL_ID]: "Search the web for up-to-date information.",
  [PYTHON_TOOL_ID]: "Execute code for complex analysis.",
  [CODING_AGENT_TOOL_ID]:
    "Investigate a GitHub repository and answer questions about its code.",
};

/** Shown for a tool with no description of its own. */
export const DEFAULT_TOOL_DESCRIPTION = "This action is not configured yet.";

/** Appended to the tooltip when the reader can configure the tool themselves. */
export const CONFIGURE_MESSAGE = "Press the settings cog to enable.";

/** Appended instead when they cannot. */
export const USER_NOT_ADMIN_MESSAGE = "Ask an admin to configure.";

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

/**
 * Stands in for absent preferences.
 *
 * One frozen array rather than a fresh `[]` each render, so the callbacks that
 * depend on it keep their identity.
 */
export const NO_DISABLED_TOOLS: number[] = [];
