import { MinimalPersonaSnapshot } from "@/app/admin/agents/interfaces";
import {
  DefaultModel,
  LLMProviderDescriptor,
  ModelConfiguration,
} from "@/interfaces/llm";
import { LlmDescriptor } from "@/lib/hooks";

export function getFinalLLM(
  llmProviders: LLMProviderDescriptor[],
  persona: MinimalPersonaSnapshot | null,
  currentLlm: LlmDescriptor | null,
  defaultText?: DefaultModel | null
): [string, string] {
  const defaultProvider = defaultText
    ? llmProviders.find((p) => p.id === defaultText.provider_id)
    : llmProviders.find((p) =>
        p.model_configurations.some((m) => m.is_visible)
      );

  let provider = defaultProvider?.provider || "";
  let model =
    defaultText?.model_name ||
    defaultProvider?.model_configurations.find((m) => m.is_visible)?.name ||
    "";

  if (persona) {
    if (persona.default_model_configuration_id != null) {
      // Canonical path: resolve provider and model from the model config ID.
      for (const p of llmProviders) {
        const mc = p.model_configurations.find(
          (m) => m.id === persona.default_model_configuration_id
        );
        if (mc) {
          provider = p.provider;
          model = mc.name;
          break;
        }
      }
    }
  }

  if (currentLlm) {
    provider = currentLlm.provider || provider;
    model = currentLlm.modelName || model;
  }

  return [provider, model];
}

export function getProviderOverrideForPersona(
  liveAgent: MinimalPersonaSnapshot,
  llmProviders: LLMProviderDescriptor[]
): LlmDescriptor | null {
  // Canonical path: resolve from model configuration ID.
  if (liveAgent.default_model_configuration_id != null) {
    for (const provider of llmProviders) {
      const mc = provider.model_configurations.find(
        (m) => m.id === liveAgent.default_model_configuration_id
      );
      if (mc) {
        return {
          name: provider.name ?? "",
          provider: provider.provider,
          modelName: mc.name,
        };
      }
    }
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

export function getDisplayName(
  agent: MinimalPersonaSnapshot,
  llmProviders: LLMProviderDescriptor[]
): string | undefined {
  if (agent.default_model_configuration_id == null) return undefined;
  for (const p of llmProviders ?? []) {
    const mc = p.model_configurations.find(
      (m) => m.id === agent.default_model_configuration_id
    );
    if (mc) return mc.display_name;
  }
  return undefined;
}
