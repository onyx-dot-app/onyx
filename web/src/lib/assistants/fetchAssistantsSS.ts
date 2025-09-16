import { Persona } from "@/app/admin/assistants/interfaces";
import { fetchSS } from "../utilsSS";
// Removed client i18n import; avoid pulling React context into server bundles
import k from "@/i18n/keys";

export type FetchAssistantsResponse = [Persona[], string | null];

export async function fetchAssistantsSS(): Promise<FetchAssistantsResponse> {
  const response = await fetchSS("/persona");
  if (response.ok) {
    return [(await response.json()) as Persona[], null];
  }
  return [[], (await response.json()).detail || "Unknown error"];
}
