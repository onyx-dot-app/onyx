import { Persona } from "@/app/admin/assistants/interfaces";

interface ShareAssistantRequest {
  userIds: string[];
  assistantId: number;
}

async function updateAssistantSharedStatus(
  request: ShareAssistantRequest
): Promise<null | string> {
  const response = await fetch(`/api/persona/${request.assistantId}/share`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      user_ids: request.userIds,
    }),
  });

  if (response.ok) {
    return null;
  }

  const errorMessage = (await response.json()).detail || "Unknown error";
  return errorMessage;
}

export async function addUsersToAssistantSharedList(
  existingAssistant: Persona,
  newUserIds: string[]
): Promise<null | string> {
  // Merge existing user IDs with new user IDs, ensuring no duplicates
  const updatedUserIds = Array.from(
    new Set([...existingAssistant.users.map((user) => user.id), ...newUserIds])
  );

  // Update the assistant's shared status with the new user list
  return updateAssistantSharedStatus({
    userIds: updatedUserIds,
    assistantId: existingAssistant.id,
  });
}

export async function removeUsersFromAssistantSharedList(
  existingAssistant: Persona,
  userIdsToRemove: string[]
): Promise<null | string> {
  // Filter out the user IDs to be removed from the existing user list
  const updatedUserIds = existingAssistant.users
    .map((user) => user.id)
    .filter((id) => !userIdsToRemove.includes(id));

  // Update the assistant's shared status with the new user list
  return updateAssistantSharedStatus({
    userIds: updatedUserIds,
    assistantId: existingAssistant.id,
  });
}
