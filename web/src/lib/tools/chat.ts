import type { MinimalAgent } from "@/lib/agents/types";
import type {
  ActionPreference,
  ToolPreference,
  ToolSnapshot,
} from "@/lib/tools/types";
import { CODING_AGENT_TOOL_ID } from "@/lib/tools/constants";

/** Incognito chats run no child agents, so the coding agent is unavailable. */
export function isBlockedInIncognito(
  tool: Pick<ToolSnapshot, "in_code_tool_id">,
  incognito: boolean
): boolean {
  return incognito && tool.in_code_tool_id === CODING_AGENT_TOOL_ID;
}

/**
 * The preference a send names: a built-in tool of the agent, else a saved
 * integration action whose integration is on, or null.
 */
export function effectiveChatPreference({
  requestedToolId,
  requestedAction,
  agent,
  incognito = false,
  isIntegrationEnabled,
}: {
  requestedToolId: number | null;
  requestedAction: ActionPreference | null;
  agent: Pick<MinimalAgent, "tools"> | undefined;
  incognito?: boolean;
  isIntegrationEnabled: (integrationId: number) => boolean;
}): ToolPreference | null {
  const tool = agent?.tools.find((entry) => entry.id === requestedToolId);
  if (tool?.in_code_tool_id && !isBlockedInIncognito(tool, incognito))
    return { type: "capability", tool_id: tool.id };
  if (requestedAction && isIntegrationEnabled(requestedAction.integration_id))
    return requestedAction;
  return null;
}
