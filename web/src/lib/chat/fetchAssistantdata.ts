import { fetchSS } from "@/lib/utilsSS";
import { Persona } from "@/app/admin/assistants/interfaces";
import { fetchLLMProvidersSS } from "@/lib/llm/fetchLLMs";
import { personaComparator } from "@/app/admin/assistants/lib";
import { fetchAssistantsSS } from "../assistants/fetchAssistantsSS";
import { checkLLMSupportsImageInput } from "../llm/utils";

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
      console.error(`Failed to fetch assistants - ${assistantsFetchError}`);
      return defaultState;
    }

    // Parallel fetch of additional data
    const [ccPairsResponse, llmProviders] = await Promise.all([
      fetchSS("/manage/indexing-status").catch((error) => {
        console.error("Failed to fetch connectors:", error);
        return null;
      }),
      fetchLLMProvidersSS().catch((error) => {
        console.error("Failed to fetch LLM providers:", error);
        return [];
      }),
    ]);

    // Process visible assistants
    let filteredAssistants = assistants.filter(
      (assistant) => assistant.is_visible
    );

    // Process connector status
    const hasAnyConnectors = ccPairsResponse?.ok
      ? (await ccPairsResponse.json()).length > 0
      : false;

    // Filter assistants based on connector status
    if (!hasAnyConnectors) {
      filteredAssistants = filteredAssistants.filter(
        (assistant) => assistant.num_chunks === 0
      );
    }

    // Sort assistants
    filteredAssistants.sort(personaComparator);

    // Check for image-compatible models
    const hasImageCompatibleModel = llmProviders.some(
      (provider) =>
        provider.provider === "openai" ||
        provider.model_names.some((model) => checkLLMSupportsImageInput(model))
    );

    // Filter out image generation tools if no compatible model
    if (!hasImageCompatibleModel) {
      filteredAssistants = filteredAssistants.filter(
        (assistant) =>
          !assistant.tools.some(
            (tool) => tool.in_code_tool_id === "ImageGenerationTool"
          )
      );
    }

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
