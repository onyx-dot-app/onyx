import { MinimalPersonaSnapshot } from "@/app/admin/agents/interfaces";
import { SEARCH_TOOL_ID } from "@/app/app/components/tools/constants";
import { UserSpecificAgentPreference } from "@/lib/types";

/**
 * Decide which tool IDs should be pre-forced when the user switches to an agent.
 *
 * For agents that have knowledge attached (document sets, hierarchy nodes,
 * attached documents, or user files) and expose the internal-search tool,
 * pre-force that tool so the LLM actually uses the configured corpus instead
 * of silently answering from model priors (#7314, #9303).
 *
 * Respects an existing per-user-per-agent disable: if the user has already
 * disabled the internal-search tool for this agent via their preferences,
 * we do not re-enable it.
 */
export function computeInitialForcedToolIds(
  agent: MinimalPersonaSnapshot,
  agentPreference: UserSpecificAgentPreference | undefined
): number[] {
  if (!agent.knowledge_sources || agent.knowledge_sources.length === 0) {
    return [];
  }

  const internalSearchTool = agent.tools.find(
    (tool) => tool.in_code_tool_id === SEARCH_TOOL_ID && !tool.mcp_server_id
  );
  if (!internalSearchTool) {
    return [];
  }

  if (agentPreference?.disabled_tool_ids?.includes(internalSearchTool.id)) {
    return [];
  }

  return [internalSearchTool.id];
}
