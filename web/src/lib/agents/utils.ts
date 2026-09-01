import { User } from "@/lib/types";
import { checkUserIsNoAuthUser } from "@/lib/users/svc";
import { MinimalAgent, Agent } from "@/lib/agents/types";
import { DEFAULT_AGENT_ID } from "@/lib/constants";

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

/**
 * Whether this is the built-in Assistant (id 0) rather than a chosen agent —
 * the "plain chat" case, which the UI shows without an agent description or a
 * named greeting.
 *
 * A missing agent is not the Assistant. Callers that treat an unresolved agent
 * as plain chat — to avoid flashing a named-agent layout for an agent that is
 * not there yet — should say so themselves.
 */
export function isAssistant(agent: MinimalAgent | undefined): boolean {
  return agent?.id === DEFAULT_AGENT_ID;
}
