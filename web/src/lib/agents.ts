import {
  MinimalPersonaSnapshot,
  Persona,
} from "@/app/admin/assistants/interfaces";
import { User } from "./types";
import { checkUserIsNoAuthUser } from "./user";
import { personaComparator } from "@/app/admin/assistants/lib";

// Check ownership
export function checkUserOwnsAssistant(
  user: User | null,
  assistant: MinimalPersonaSnapshot | Persona
) {
  return checkUserIdOwnsAssistant(user?.id, assistant);
}

export function checkUserIdOwnsAssistant(
  userId: string | undefined,
  assistant: MinimalPersonaSnapshot | Persona
) {
  return (
    (!userId ||
      checkUserIsNoAuthUser(userId) ||
      assistant.owner?.id === userId) &&
    !assistant.builtin_persona
  );
}

// Pin agents
export async function pinAgents(pinnedAgentIds: number[]) {
  const response = await fetch(`/api/user/pinned-assistants`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      ordered_assistant_ids: pinnedAgentIds,
    }),
  });
  if (!response.ok) {
    throw new Error("Failed to update pinned assistants");
  }
}

// Filter assistants based on connector status, image compatibility and visibility
export function filterAssistants(
  assistants: MinimalPersonaSnapshot[]
): MinimalPersonaSnapshot[] {
  let filteredAssistants = assistants.filter(
    (assistant) => assistant.is_visible
  );
  return filteredAssistants.sort(personaComparator);
}

/**
 * Updates agent sharing settings.
 *
 * For MIT versions, group_ids should not be sent since group-based sharing
 * is an EE-only feature.
 *
 * @param agentId - The ID of the agent to update
 * @param userIds - Array of user IDs to share with
 * @param groupIds - Array of group IDs to share with (ignored when isPaidEnterpriseFeaturesEnabled is false)
 * @param isPublic - Whether the agent should be public
 * @param isPaidEnterpriseFeaturesEnabled - Whether enterprise features are enabled
 * @returns null on success, or an error message string on failure
 *
 * @example
 * const isPaidEnterpriseFeaturesEnabled = usePaidEnterpriseFeaturesEnabled();
 * const error = await updateAgentSharedStatus(agentId, userIds, groupIds, isPublic, isPaidEnterpriseFeaturesEnabled);
 * if (error) console.error(error);
 */
export async function updateAgentSharedStatus(
  agentId: number,
  userIds: string[],
  groupIds: number[],
  isPublic: boolean | undefined,
  isPaidEnterpriseFeaturesEnabled: boolean
): Promise<null | string> {
  // MIT versions should not send group_ids - warn if caller provided non-empty groups
  if (!isPaidEnterpriseFeaturesEnabled && groupIds.length > 0) {
    console.error(
      "updateAgentSharedStatus: groupIds provided but enterprise features are disabled. " +
        "Group sharing is an EE-only feature. Discarding groupIds."
    );
  }

  try {
    const response = await fetch(`/api/persona/${agentId}/share`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        user_ids: userIds,
        // Only include group_ids for enterprise versions
        group_ids: isPaidEnterpriseFeaturesEnabled ? groupIds : undefined,
        is_public: isPublic,
      }),
    });

    if (response.ok) {
      return null;
    }

    const errorMessage = (await response.json()).detail || "Unknown error";
    return errorMessage;
  } catch (error) {
    console.error("updateAgentSharedStatus: Network error", error);
    return "Network error. Please check your connection and try again.";
  }
}
