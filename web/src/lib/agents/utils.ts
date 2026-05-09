import { User } from "@/lib/types";
import { checkUserIsNoAuthUser } from "@/lib/user";
import { MinimalAgentSnapshot, Persona } from "@/lib/agents/types";

export function checkUserOwnsAgent(
  user: User | null,
  agent: MinimalAgentSnapshot | Persona
): boolean {
  if (!user) return false;
  const userId = user.id;
  return (
    !!userId &&
    (checkUserIsNoAuthUser(userId) || agent.owner?.id === userId) &&
    !agent.builtin_persona
  );
}

export function buildAgentAvatarUrl(agentId: number) {
  return `/api/persona/${agentId}/avatar`;
}
