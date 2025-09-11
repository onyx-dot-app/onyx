import { Persona } from "@/app/admin/assistants/interfaces";
import { fetchSS } from "../utilsSS";
import i18n from "@/i18n/init";
import k from "@/i18n/keys";

export type FetchAssistantsResponse = [Persona[], string | null];

export async function fetchAssistantsSS(): Promise<FetchAssistantsResponse> {
  const response = await fetchSS("/persona");
  if (response.ok) {
    return [(await response.json()) as Persona[], null];
  }
  return [[], (await response.json()).detail || i18n.t(k.UNKNOWN_ERROR)];
}
