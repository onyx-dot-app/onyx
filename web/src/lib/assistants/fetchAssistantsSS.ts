import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { fetchSS } from "../utilsSS";

export type FetchAssistantsResponse = [MinimalPersonaSnapshot[], string | null];

export async function fetchAssistantsSS(): Promise<FetchAssistantsResponse> {
  const response = await fetchSS("/persona");
  if (response.ok) {
    return [(await response.json()) as MinimalPersonaSnapshot[], null];
  }
  return [[], (await response.json()).detail || "Unknown Error"];
}
