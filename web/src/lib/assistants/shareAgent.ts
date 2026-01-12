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
