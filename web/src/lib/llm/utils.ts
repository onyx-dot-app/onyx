import { Persona } from "@/app/admin/assistants/interfaces";
import { LLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import { LlmOverride } from "@/lib/hooks";

export function getFinalLLM(
  llmProviders: LLMProviderDescriptor[],
  persona: Persona | null,
  llmOverride: LlmOverride | null
): [string, string] {
  const defaultProvider = llmProviders.find(
    (llmProvider) => llmProvider.is_default_provider
  );

  let provider = defaultProvider?.provider || "";
  let model = defaultProvider?.default_model_name || "";

  if (persona) {
    // Map "provider override" to actual LLLMProvider
    if (persona.llm_model_provider_override) {
      const underlyingProvider = llmProviders.find(
        (item: LLMProviderDescriptor) =>
          item.name === persona.llm_model_provider_override
      );
      provider = underlyingProvider?.provider || provider;
    }
    model = persona.llm_model_version_override || model;
  }

  if (llmOverride) {
    provider = llmOverride.provider || provider;
    model = llmOverride.modelName || model;
  }

  return [provider, model];
}

export function getLLMProviderOverrideForPersona(
  liveAssistant: Persona,
  llmProviders: LLMProviderDescriptor[]
): LlmOverride | null {
  const overrideProvider = liveAssistant.llm_model_provider_override;
  const overrideModel = liveAssistant.llm_model_version_override;

  if (!overrideModel) {
    return null;
  }

  const matchingProvider = llmProviders.find(
    (provider) =>
      (overrideProvider ? provider.name === overrideProvider : true) &&
      provider.model_names.includes(overrideModel)
  );

  if (matchingProvider) {
    return {
      name: matchingProvider.name,
      provider: matchingProvider.provider,
      modelName: overrideModel,
    };
  }

  return null;
}

const MODELS_SUPPORTING_IMAGES = [
  ["openai", "gpt-4o"],
  ["openai", "gpt-4o-mini"],
  ["openai", "gpt-4-vision-preview"],
  ["openai", "gpt-4-turbo"],
  ["openai", "gpt-4-1106-vision-preview"],
  ["azure", "gpt-4o"],
  ["azure", "gpt-4o-mini"],
  ["azure", "gpt-4-vision-preview"],
  ["azure", "gpt-4-turbo"],
  ["azure", "gpt-4-1106-vision-preview"],
];

export function checkLLMSupportsImageInput(provider: string, model: string) {
  return MODELS_SUPPORTING_IMAGES.some(
    ([p, m]) => p === provider && m === model
  );
}

export const structureValue = (
  name: string,
  provider: string,
  modelName: string
) => {
  return `${name}__${provider}__${modelName}`;
};

export const destructureValue = (value: string): LlmOverride => {
  const [displayName, provider, modelName] = value.split("__");
  return {
    name: displayName,
    provider,
    modelName,
  };
};
