import { User } from "@/lib/types";
import { checkUserIsNoAuthUser } from "@/lib/user";
import { MinimalPersonaSnapshot, Persona } from "@/lib/agents/types";

export function checkUserOwnsAgent(
  user: User | null,
  agent: MinimalPersonaSnapshot | Persona
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
