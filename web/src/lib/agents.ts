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
