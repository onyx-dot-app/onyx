import { MinimalPersonaSnapshot } from "@/app/admin/agents/interfaces";
import { filterAgents } from "@/lib/agents";
import { fetchAgentsSS } from "@/lib/agentsSS";

export async function fetchAgentData(): Promise<MinimalPersonaSnapshot[]> {
  try {
    // Fetch core assistants data
    const [assistants, agentsFetchError] = await fetchAgentsSS();
    if (agentsFetchError) {
      // This is not a critical error and occurs when the user is not logged in
      console.warn(`Failed to fetch agents - ${agentsFetchError}`);
      return [];
    }

    return filterAgents(assistants);
  } catch (error) {
    console.error("Unexpected error in fetchAgentData:", error);
    return [];
  }
}
