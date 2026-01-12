import { Persona } from "@/app/admin/assistants/interfaces";

interface ShareAgentRequest {
  userIds: string[];
  groupIds: number[];
  agentId: number;
}

async function updateAgentSharedStatus(
  request: ShareAgentRequest
): Promise<null | string> {
  const response = await fetch(`/api/persona/${request.agentId}/share`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      user_ids: request.userIds,
      group_ids: request.groupIds,
    }),
  });

  if (response.ok) {
    return null;
  }

  const errorMessage = (await response.json()).detail || "Unknown error";
  return errorMessage;
}

export async function addUsersToAgentSharedList(
  existingAgent: Persona,
  newUserIds: string[],
  newGroupIds: number[] = []
): Promise<null | string> {
  // Merge existing user IDs with new user IDs, ensuring no duplicates
  const updatedUserIds = Array.from(
    new Set([...existingAgent.users.map((user) => user.id), ...newUserIds])
  );

  // Merge existing group IDs with new group IDs, ensuring no duplicates
  const updatedGroupIds = Array.from(
    new Set([...existingAgent.groups, ...newGroupIds])
  );

  // Update the agent's shared status with the new user and group lists
  return updateAgentSharedStatus({
    userIds: updatedUserIds,
    groupIds: updatedGroupIds,
    agentId: existingAgent.id,
  });
}

export async function removeUsersFromAgentSharedList(
  existingAgent: Persona,
  userIdsToRemove: string[],
  groupIdsToRemove: number[] = []
): Promise<null | string> {
  // Filter out the user IDs to be removed from the existing user list
  const updatedUserIds = existingAgent.users
    .map((user) => user.id)
    .filter((id) => !userIdsToRemove.includes(id));

  // Filter out the group IDs to be removed from the existing group list
  const updatedGroupIds = existingAgent.groups.filter(
    (id) => !groupIdsToRemove.includes(id)
  );

  // Update the agent's shared status with the new user and group lists
  return updateAgentSharedStatus({
    userIds: updatedUserIds,
    groupIds: updatedGroupIds,
    agentId: existingAgent.id,
  });
}
