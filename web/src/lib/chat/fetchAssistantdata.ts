import { fetchSS } from "@/lib/utilsSS";
import { CCPairBasicInfo } from "@/lib/types";
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
  const [assistants, assistantsFetchError] = await fetchAssistantsSS();
  const ccPairsResponse = await fetchSS("/manage/indexing-status");

  let ccPairs: CCPairBasicInfo[] = [];
  if (ccPairsResponse?.ok) {
    ccPairs = await ccPairsResponse.json();
  } else {
    console.log(`Failed to fetch connectors - ${ccPairsResponse?.status}`);
  }

  const hasAnyConnectors = ccPairs.length > 0;

  // if no connectors are setup, only show personas that are pure
  // passthrough and don't do any retrieval
  let filteredAssistants = assistants;
  if (assistantsFetchError) {
    console.log(`Failed to fetch assistants - ${assistantsFetchError}`);
  }

  // remove those marked as hidden by an admin
  filteredAssistants = filteredAssistants.filter(
    (assistant) => assistant.is_visible
  );

  if (!hasAnyConnectors) {
    filteredAssistants = filteredAssistants.filter(
      (assistant) => assistant.num_chunks === 0
    );
  }

  // sort them in priority order
  filteredAssistants.sort(personaComparator);

  const llmProviders = await fetchLLMProvidersSS();
  const hasImageCompatibleModel = llmProviders.some(
    (provider) =>
      provider.provider === "openai" ||
      provider.model_names.some((model) => checkLLMSupportsImageInput(model))
  );

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
}
