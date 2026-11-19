import type { MinimalAgent } from "@/lib/agents/types";
import type { ActionPreference, ToolPreference } from "@/lib/tools/types";

/**
 * The preference a send names: a built-in tool of the agent, else a saved
 * plugin action whose plugin is on, or null.
 */
export function effectiveChatPreference({
  requestedToolId,
  requestedAction,
  agent,
  isPluginEnabled,
}: {
  requestedToolId: number | null;
  requestedAction: ActionPreference | null;
  agent: Pick<MinimalAgent, "tools"> | undefined;
  isPluginEnabled: (pluginId: string) => boolean;
}): ToolPreference | null {
  const tool = agent?.tools.find((entry) => entry.id === requestedToolId);
  if (tool?.in_code_tool_id) return { type: "capability", tool_id: tool.id };
  if (requestedAction && isPluginEnabled(requestedAction.plugin_id))
    return requestedAction;
  return null;
}
