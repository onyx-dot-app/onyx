import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { fetchAssistantsSS } from "../assistants/fetchAssistantsSS";
import { filterAssistants } from "../assistants/utils";

export async function fetchAssistantData(): Promise<MinimalPersonaSnapshot[]> {
  try {
    // Fetch core assistants data
    const [assistants, assistantsFetchError] = await fetchAssistantsSS();
    if (assistantsFetchError) {
      // This is not a critical error and occurs when the user is not logged in
      console.warn(`Failed to fetch assistants - ${assistantsFetchError}`);
      return [];
    }

    return filterAssistants(assistants);
  } catch (error) {
    console.error("Unexpected error in fetchAssistantData:", error);
    return [];
  }
}
