import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import {
  LLMProviderDescriptor,
  ModelConfiguration,
} from "@/app/admin/configuration/llm/interfaces";
import { LlmDescriptor } from "@/lib/hooks";

export function getFinalLLM(
  llmProviders: LLMProviderDescriptor[],
  persona: MinimalPersonaSnapshot | null,
  currentLlm: LlmDescriptor | null
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

  if (currentLlm) {
    provider = currentLlm.provider || provider;
    model = currentLlm.modelName || model;
  }

  return [provider, model];
}

export function getLLMProviderOverrideForPersona(
  liveAssistant: MinimalPersonaSnapshot,
  llmProviders: LLMProviderDescriptor[]
): LlmDescriptor | null {
  const overrideProvider = liveAssistant.llm_model_provider_override;
  const overrideModel = liveAssistant.llm_model_version_override;

  if (!overrideModel) {
    return null;
  }

  const matchingProvider = llmProviders.find(
    (provider) =>
      (overrideProvider ? provider.name === overrideProvider : true) &&
      provider.model_configurations
        .map((modelConfiguration) => modelConfiguration.name)
        .includes(overrideModel)
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

export const structureValue = (
  name: string,
  provider: string,
  modelName: string
) => {
  return `${name}__${provider}__${modelName}`;
};

export const parseLlmDescriptor = (value: string): LlmDescriptor => {
  const [displayName, provider, modelName] = value.split("__");
  if (displayName === undefined) {
    return { name: "Unknown", provider: "", modelName: "" };
  }

  return {
    name: displayName,
    provider: provider ?? "",
    modelName: modelName ?? "",
  };
};

export const findProviderForModel = (
  llmProviders: LLMProviderDescriptor[],
  modelName: string
): string => {
  const provider = llmProviders.find((p) =>
    p.model_configurations
      .map((modelConfiguration) => modelConfiguration.name)
      .includes(modelName)
  );
  return provider ? provider.provider : "";
};

export const findModelInModelConfigurations = (
  modelConfigurations: ModelConfiguration[],
  modelName: string
): ModelConfiguration | null => {
  return modelConfigurations.find((m) => m.name === modelName) || null;
};

export const findModelConfiguration = (
  llmProviders: LLMProviderDescriptor[],
  modelName: string,
  providerName: string | null = null
): ModelConfiguration | null => {
  if (providerName) {
    const provider = llmProviders.find((p) => p.name === providerName);
    return provider
      ? findModelInModelConfigurations(provider.model_configurations, modelName)
      : null;
  }

  for (const provider of llmProviders) {
    const modelConfiguration = findModelInModelConfigurations(
      provider.model_configurations,
      modelName
    );
    if (modelConfiguration) {
      return modelConfiguration;
    }
  }

  return null;
};

export const modelSupportsImageInput = (
  llmProviders: LLMProviderDescriptor[],
  modelName: string,
  providerName: string | null = null
): boolean => {
  const modelConfiguration = findModelConfiguration(
    llmProviders,
    modelName,
    providerName
  );
  return modelConfiguration?.supports_image_input || false;
};
