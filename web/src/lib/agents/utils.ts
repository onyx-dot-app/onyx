import { User } from "@/lib/types";
import { checkUserIsNoAuthUser } from "@/lib/user";
import { MinimalAgent, Agent } from "@/lib/agents/types";

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

// TODO: rename to agent — https://linear.app/onyx-app/issue/ENG-3766
export function buildAgentAvatarUrl(agentId: number) {
  return `/api/persona/${agentId}/avatar`;
}

// TODO: rename to agent — https://linear.app/onyx-app/issue/ENG-3766
export function buildUpdateAgentPreferenceUrl(agentId: number) {
  return `/api/user/assistant/${agentId}/preferences`;
}
