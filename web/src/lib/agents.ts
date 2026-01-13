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

// Share agent
export default async function updateAgentSharedStatus(
  agentId: number,
  userIds: string[],
  groupIds: number[],
  isPublic?: boolean
): Promise<null | string> {
  const response = await fetch(`/api/persona/${agentId}/share`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      user_ids: userIds,
      group_ids: groupIds,
      is_public: isPublic,
    }),
  });

  if (response.ok) {
    return null;
  }

  const errorMessage = (await response.json()).detail || "Unknown error";
  return errorMessage;
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
