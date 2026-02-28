import { MinimalPersonaSnapshot } from "@/app/admin/agents/interfaces";
import { fetchSS } from "./utilsSS";

export type FetchAgentsResponse = [MinimalPersonaSnapshot[], string | null];

// Fetch agents server-side
export async function fetchAgentsSS(): Promise<FetchAgentsResponse> {
  const response = await fetchSS("/persona");
  if (response.ok) {
    return [(await response.json()) as MinimalPersonaSnapshot[], null];
  }
  return [[], (await response.json()).detail || "Unknown Error"];
}
