import { User } from "@/lib/types";
import { checkUserIsNoAuthUser } from "@/lib/user";
import { MinimalAgent, Agent } from "@/lib/agents/types";

/**
 * Returns true if the user owns the agent and may edit or delete it.
 * No-auth users are treated as owning all non-builtin agents.
 * Built-in agents are never owned by anyone.
 */
export function checkUserOwnsAgent(
  user: User | null,
  agent: MinimalAgent | Agent
): boolean {
  if (!user) return false;
  const userId = user.id;
  return (
    !!userId &&
    (checkUserIsNoAuthUser(userId) || agent.owner?.id === userId) &&
    !agent.builtin_persona
  );
}

// TODO(ENG-3766): rename to agent
/** Returns the URL for an agent's avatar image. */
export function buildAgentAvatarUrl(agentId: number) {
  return `/api/persona/${agentId}/avatar`;
}

// TODO(ENG-3766): rename to agent
/** Returns the URL for patching a user's per-agent preferences. */
export function buildUpdateAgentPreferenceUrl(agentId: number) {
  return `/api/user/assistant/${agentId}/preferences`;
}
