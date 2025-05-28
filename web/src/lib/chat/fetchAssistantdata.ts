import { fetchSS } from "@/lib/utilsSS";
import { Persona } from "@/app/admin/assistants/interfaces";
import { fetchLLMProvidersSS } from "@/lib/llm/fetchLLMs";
import { fetchAssistantsSS } from "../assistants/fetchAssistantsSS";
import { modelSupportsImageInput } from "../llm/utils";
import { filterAssistants } from "../assistants/utils";

interface AssistantData {
  assistants: Persona[];
  hasAnyConnectors: boolean;
  hasImageCompatibleModel: boolean;
}
export async function fetchAssistantData(): Promise<AssistantData> {
  // Default state if anything fails
  const defaultState: AssistantData = {
    assistants: [],
    hasAnyConnectors: false,
    hasImageCompatibleModel: false,
  };

  try {
    // Fetch core assistants data first
    const [assistants, assistantsFetchError] = await fetchAssistantsSS();
    if (assistantsFetchError) {
      // This is not a critical error and occurs when the user is not logged in
      console.warn(`Failed to fetch assistants - ${assistantsFetchError}`);
      return defaultState;
    }

    // Parallel fetch of additional data
    const [ccPairsResponse, llmProviders] = await Promise.all([
      fetchSS("/manage/connector-status").catch((error) => {
        console.error("Failed to fetch connectors:", error);
        return null;
      }),
      fetchLLMProvidersSS().catch((error) => {
        console.error("Failed to fetch LLM providers:", error);
        return [];
      }),
    ]);

    const hasAnyConnectors = ccPairsResponse?.ok
      ? (await ccPairsResponse.json()).length > 0
      : false;

    const hasImageCompatibleModel = llmProviders.some(
      (provider) =>
        provider.provider === "openai" ||
        provider.model_configurations.some((modelConfiguration) =>
          modelSupportsImageInput(llmProviders, modelConfiguration.name)
        )
    );

    let filteredAssistants = filterAssistants(
      assistants,
      hasAnyConnectors,
      hasImageCompatibleModel
    );

    return {
      assistants: filteredAssistants,
      hasAnyConnectors,
      hasImageCompatibleModel,
    };
  } catch (error) {
    console.error("Unexpected error in fetchAssistantData:", error);
    return defaultState;
  }
}
