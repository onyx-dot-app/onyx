import { ToolSnapshot } from "@/lib/tools/interfaces";
import { OPEN_URL_TOOL_ID } from "./constants";

/**
 * Configuration for tool visibility across different UI contexts.
 * This matches the backend TOOL_VISIBILITY_CONFIG structure in backend/onyx/server/features/tool/models.py.
 */
export interface ToolVisibilitySettings {
  /** Whether tool appears in chat input bar dropdown (ActionsPopover) */
  chatSelectable: boolean;
  /** Whether tool appears in agent creation/default behavior pages */
  agentCreationSelectable: boolean;
  /** Whether tool is enabled by default */
  defaultEnabled: boolean;
}

/**
 * Centralized configuration for tool visibility across different contexts.
 * This allows for easy extension with new tools that need custom visibility rules.
 *
 * To add a new tool with custom visibility:
 * 1. Add entry here with the tool's in_code_tool_id
 * 2. Update the corresponding backend TOOL_VISIBILITY_CONFIG in backend/onyx/server/features/tool/models.py
 */
export const TOOL_VISIBILITY_CONFIG: Record<string, ToolVisibilitySettings> = {
  [OPEN_URL_TOOL_ID]: {
    chatSelectable: false,
    agentCreationSelectable: true,
    defaultEnabled: true,
  },
  // Future tools can be added here with custom visibility rules
};

export function isChatSelectable(tool: ToolSnapshot): boolean {
  // Custom tools (no in_code_tool_id) are always chat selectable
  if (!tool.in_code_tool_id) {
    return true;
  }

  const config = TOOL_VISIBILITY_CONFIG[tool.in_code_tool_id];
  return config?.chatSelectable ?? true;
}

export function isAgentCreationSelectable(tool: ToolSnapshot): boolean {
  // Custom tools (no in_code_tool_id) are always agent creation selectable
  if (!tool.in_code_tool_id) {
    return true;
  }

  const config = TOOL_VISIBILITY_CONFIG[tool.in_code_tool_id];
  return config?.agentCreationSelectable ?? true;
}

export function isDefaultEnabled(tool: ToolSnapshot): boolean {
  // Custom tools default to false
  if (!tool.in_code_tool_id) {
    return false;
  }

  const config = TOOL_VISIBILITY_CONFIG[tool.in_code_tool_id];
  return config?.defaultEnabled ?? false;
}
