import {
  MinimalPersonaSnapshot,
  Persona,
} from "@/app/admin/assistants/interfaces";
import { User } from "./types";
import { checkUserIsNoAuthUser } from "./user";
import { personaComparator } from "@/app/admin/assistants/lib";

/**
 * Checks if the given user owns the specified assistant.
 *
 * @param user - The user to check ownership for, or null if no user is logged in
 * @param assistant - The assistant to check ownership of
 * @returns true if the user owns the assistant (or no auth is required), false otherwise
 */
export function checkUserOwnsAssistant(
  user: User | null,
  assistant: MinimalPersonaSnapshot | Persona
) {
  return checkUserIdOwnsAssistant(user?.id, assistant);
}

/**
 * Checks if the given user ID owns the specified assistant.
 *
 * Returns true if a valid user ID is provided and any of the following conditions
 * are met (and the assistant is not built-in):
 * - The user is a no-auth user (authentication is disabled)
 * - The user ID matches the assistant owner's ID
 *
 * Returns false if userId is undefined (e.g., user is loading or unauthenticated)
 * to prevent granting ownership access prematurely.
 *
 * @param userId - The user ID to check ownership for
 * @param assistant - The assistant to check ownership of
 * @returns true if the user owns the assistant, false otherwise
 */
export function checkUserIdOwnsAssistant(
  userId: string | undefined,
  assistant: MinimalPersonaSnapshot | Persona
) {
  return (
    !!userId &&
    (checkUserIsNoAuthUser(userId) || assistant.owner?.id === userId) &&
    !assistant.builtin_persona
  );
}

/**
 * Updates the user's pinned assistants with the given ordered list of agent IDs.
 *
 * @param pinnedAgentIds - Array of agent IDs in the desired pinned order
 * @throws Error if the API request fails
 */
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

/**
 * Filters and sorts assistants based on visibility.
 *
 * Only returns assistants that are marked as visible, sorted using the persona comparator.
 *
 * @param assistants - Array of assistants to filter
 * @returns Filtered and sorted array of visible assistants
 */
export function filterAssistants(
  assistants: MinimalPersonaSnapshot[]
): MinimalPersonaSnapshot[] {
  let filteredAssistants = assistants.filter(
    (assistant) => assistant.is_visible
  );
  return filteredAssistants.sort(personaComparator);
}

/**
 * Deletes an agent by its ID.
 *
 * @param agentId - The ID of the agent to delete
 * @returns null on success, or an error message string on failure
 */
export async function deleteAgent(agentId: number): Promise<string | null> {
  try {
    const response = await fetch(`/api/persona/${agentId}`, {
      method: "DELETE",
    });

    if (response.ok) {
      return null;
    }

    const errorMessage = (await response.json()).detail || "Unknown error";
    return errorMessage;
  } catch (error) {
    console.error("deleteAgent: Network error", error);
    return "Network error. Please check your connection and try again.";
  }
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
  isPaidEnterpriseFeaturesEnabled: boolean,
  labelIds?: number[]
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
        label_ids: labelIds,
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

/**
 * Updates the labels assigned to an agent via the share endpoint.
 *
 * @param agentId - The ID of the agent to update
 * @param labelIds - Array of label IDs to assign to the agent
 * @returns null on success, or an error message string on failure
 */
export async function updateAgentLabels(
  agentId: number,
  labelIds: number[]
): Promise<string | null> {
  try {
    const response = await fetch(`/api/persona/${agentId}/share`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label_ids: labelIds }),
    });

    if (response.ok) {
      return null;
    }

    const errorMessage = (await response.json()).detail || "Unknown error";
    return errorMessage;
  } catch (error) {
    console.error("updateAgentLabels: Network error", error);
    return "Network error. Please check your connection and try again.";
  }
}

/**
 * Updates the featured (default) status of an agent.
 *
 * @param agentId - The ID of the agent to update
 * @param isFeatured - Whether the agent should be featured
 * @returns null on success, or an error message string on failure
 */
export async function updateAgentFeaturedStatus(
  agentId: number,
  isFeatured: boolean
): Promise<string | null> {
  try {
    const response = await fetch(`/api/admin/persona/${agentId}/default`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_default_persona: isFeatured }),
    });

    if (response.ok) {
      return null;
    }

    const errorMessage = (await response.json()).detail || "Unknown error";
    return errorMessage;
  } catch (error) {
    console.error("updateAgentFeaturedStatus: Network error", error);
    return "Network error. Please check your connection and try again.";
  }
}
