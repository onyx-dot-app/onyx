export default async function deleteAgent(
  agentId: number
): Promise<null | string> {
  const response = await fetch(`/api/persona/${agentId}`, {
    method: "DELETE",
  });

  if (response.ok) {
    return null;
  }

  const errorMessage = (await response.json()).detail || "Unknown error";
  return errorMessage;
}
