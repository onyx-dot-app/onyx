import type { MinimalAgent } from "@/lib/agents/types";
import type { ToolSnapshot } from "@/lib/tools/types";
import { CODING_AGENT_TOOL_ID } from "@/lib/tools/constants";

/** Incognito chats run no child agents, so the coding agent is unavailable. */
export function isBlockedInIncognito(
  tool: Pick<ToolSnapshot, "in_code_tool_id">,
  incognito: boolean
): boolean {
  return incognito && tool.in_code_tool_id === CODING_AGENT_TOOL_ID;
}

/** The preferred tool a send names: a built-in tool of the agent, or null. */
export function effectiveChatPreferredToolId({
  requestedToolId,
  agent,
  incognito = false,
}: {
  requestedToolId: number | null;
  agent: Pick<MinimalAgent, "tools"> | undefined;
  incognito?: boolean;
}): number | null {
  const tool = agent?.tools.find((entry) => entry.id === requestedToolId);
  if (!tool || !tool.in_code_tool_id || isBlockedInIncognito(tool, incognito))
    return null;
  return tool.id;
}
