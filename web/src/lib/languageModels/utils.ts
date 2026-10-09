import type { IconFunctionComponent } from "@opal/types";
import { SvgCpu } from "@opal/icons";
import { MinimalAgent } from "@/lib/agents/types";
import {
  AGGREGATOR_PROVIDERS,
  CUSTOM_CONFIG_OVERRIDES,
  DEFAULT_ENTRY,
  MODEL_ICON_MAP,
  PROVIDERS,
} from "@/lib/languageModels/constants";
import CustomModal from "@/sections/modals/languageModels/CustomModal";
import type {
  DefaultModel,
  LLMProviderDescriptor,
  LLMProviderView,
  ModelConfiguration,
  ProviderEntry,
} from "@/lib/languageModels/types";
import { LlmDescriptor } from "@/lib/hooks";

/**
 * Find the provider that owns a given model configuration.
 *
 * `llm_provider.name` has no unique constraint, so two providers can share a
 * display name. Matching a provider by name and then posting its id sends the
 * wrong `provider_id` whenever the first name match is not the row that owns
 * the model. `model_configuration.id` is a primary key, so it always is.
 */
export function findProviderOwningModelConfig<
  T extends { id: number; model_configurations: ModelConfiguration[] },
>(
  llmProviders: T[] | undefined,
  modelConfigurationId: number | null | undefined
): T | undefined {
  if (modelConfigurationId == null) return undefined;
  return llmProviders?.find((provider) =>
    provider.model_configurations.some((mc) => mc.id === modelConfigurationId)
  );
}

export function hasVisibleLLMModel(
  llmProviders: LLMProviderDescriptor[] | undefined
): boolean {
  return (
    llmProviders?.some((provider) =>
      provider.model_configurations.some((model) => model.is_visible)
    ) ?? false
  );
}

export function getFinalLLM(
  llmProviders: LLMProviderDescriptor[],
  agent: MinimalAgent | null,
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

  if (agent) {
    if (agent.default_model_configuration_id != null) {
      // Canonical path: resolve provider and model from the model config ID.
      for (const p of llmProviders) {
        const mc = p.model_configurations.find(
          (m) => m.id === agent.default_model_configuration_id
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

export function getProviderOverrideForAgent(
  activeAgent: MinimalAgent,
  llmProviders: LLMProviderDescriptor[]
): LlmDescriptor | null {
  // Canonical path: resolve from model configuration ID.
  if (activeAgent.default_model_configuration_id != null) {
    for (const provider of llmProviders) {
      const mc = provider.model_configurations.find(
        (m) => m.id === activeAgent.default_model_configuration_id
      );
      if (mc) {
        return {
          name: provider.name ?? "",
          provider: provider.provider,
          modelName: mc.name,
          modelConfigurationId: mc.id,
        };
      }
    }
  }

  return null;
}

export const structureValue = (
  name: string,
  provider: string,
  modelName: string,
  modelConfigurationId?: number | null
) => {
  const base = `${name}__${provider}__${modelName}`;
  // "mc:" marks the segment as an id so legacy model names that happen to
  // contain "__<digits>" can never be misread as one.
  return modelConfigurationId != null
    ? `${base}__mc:${modelConfigurationId}`
    : base;
};

export const parseLlmDescriptor = (value: string): LlmDescriptor => {
  const parts = value.split("__");
  const displayName = parts[0];
  if (displayName === undefined) {
    return { name: "Unknown", provider: "", modelName: "" };
  }

  // The id is always the marked last segment; everything between the provider
  // and it belongs to the model name, which may itself contain "__".
  const last = parts[parts.length - 1];
  const hasId =
    parts.length >= 4 && last !== undefined && /^mc:\d+$/.test(last);
  const modelName = parts.slice(2, hasId ? -1 : undefined).join("__");

  return {
    name: displayName,
    provider: parts[1] ?? "",
    modelName,
    modelConfigurationId: hasId ? parseInt(last!.slice(3), 10) : undefined,
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

/** Display name for form-state model rows, which do not reliably carry
 *  effectiveDisplayName. Everything else should read that field instead. */
export function modelDisplayName(
  model: Pick<
    ModelConfiguration,
    "name" | "display_name" | "custom_display_name"
  >
): string {
  return model.custom_display_name || model.display_name || model.name;
}

export function getDisplayName(
  agent: MinimalAgent,
  llmProviders: LLMProviderDescriptor[]
): string | undefined {
  if (agent.default_model_configuration_id == null) return undefined;
  for (const p of llmProviders ?? []) {
    const mc = p.model_configurations.find(
      (m) => m.id === agent.default_model_configuration_id
    );
    if (mc) return mc.effectiveDisplayName;
  }
  return undefined;
}

export function getProvider(
  providerName: string,
  existingProvider?: LLMProviderView
): ProviderEntry {
  const entry = PROVIDERS[providerName] ?? {
    ...DEFAULT_ENTRY,
    productName: providerName,
    companyName: providerName,
  };

  // An empty custom_config carries no signal of origin. Only a non-empty map
  // marks a provider created via the custom form.
  const customConfig = existingProvider?.custom_config;
  if (
    customConfig != null &&
    Object.keys(customConfig).length > 0 &&
    CUSTOM_CONFIG_OVERRIDES.has(providerName)
  ) {
    return { ...entry, Modal: CustomModal };
  }

  return entry;
}

/**
 * Model-aware icon resolver that checks both provider name and model name
 * to pick the most specific icon (e.g. Claude icon for a Bedrock Claude model).
 */
export function getModelIcon(
  providerName: string,
  modelName?: string
): IconFunctionComponent {
  const lowerProviderName = providerName.toLowerCase();

  // For aggregator providers, prioritise showing the vendor icon based on model name
  if (AGGREGATOR_PROVIDERS.has(lowerProviderName) && modelName) {
    const lowerModelName = modelName.toLowerCase();
    for (const [key, icon] of Object.entries(MODEL_ICON_MAP)) {
      if (lowerModelName.includes(key)) {
        return icon;
      }
    }
  }

  // Check if provider name directly matches an icon
  if (lowerProviderName in MODEL_ICON_MAP) {
    const icon = MODEL_ICON_MAP[lowerProviderName];
    if (icon) {
      return icon;
    }
  }

  // For non-aggregator providers, check if model name contains any of the keys
  if (modelName) {
    const lowerModelName = modelName.toLowerCase();
    for (const [key, icon] of Object.entries(MODEL_ICON_MAP)) {
      if (lowerModelName.includes(key)) {
        return icon;
      }
    }
  }

  // Fallback to CPU icon if no matches
  return SvgCpu;
}
