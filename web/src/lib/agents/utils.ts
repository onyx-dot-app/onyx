import { User } from "@/lib/types";
import { checkUserIsNoAuthUser } from "@/lib/user";
import { MinimalAgent, Agent } from "@/lib/agents/types";

/**
 * Returns true if the user owns the agent (directly or via an owner group —
 * the server-computed `user_permission` covers both). No-auth users are
 * treated as owning all non-builtin agents; built-ins are never owned.
 */
export function checkUserOwnsAgent(
  user: User | null,
  agent: MinimalAgent | Agent
): boolean {
  if (!user || agent.builtin_persona) return false;
  if (checkUserIsNoAuthUser(user.id)) return true;
  if (agent.user_permission != null) {
    return agent.user_permission === "OWNER";
  }
  // Fallback for payloads predating user_permission
  return agent.owner?.id === user.id;
}

/**
 * Returns true if the user may edit the agent — owner, EDITOR-level sharee,
 * or admin (admins report EDITOR server-side).
 */
export function checkUserCanEditAgent(
  user: User | null,
  agent: MinimalAgent | Agent
): boolean {
  if (!user || agent.builtin_persona) return false;
  if (checkUserIsNoAuthUser(user.id)) return true;
  if (agent.user_permission != null) {
    return (
      agent.user_permission === "OWNER" || agent.user_permission === "EDITOR"
    );
  }
  // Fallback for payloads predating user_permission: only ownership is knowable
  return agent.owner?.id === user.id;
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
