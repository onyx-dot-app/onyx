import type { IconFunctionComponent } from "@opal/types";
import { LLMProviderDescriptor } from "@/interfaces/llm";
import { getModelIcon } from "@/lib/languageModels";
import { AGGREGATOR_PROVIDERS } from "@/lib/languageModels/svc";

export interface LLMOption {
  name: string;
  provider: string;
  providerDisplayName: string;
  modelName: string;
  modelConfigurationId?: number | null;
  displayName: string;
  description?: string;
  vendor: string | null;
  maxInputTokens?: number | null;
  region?: string | null;
  version?: string | null;
  supportsReasoning?: boolean;
  supportsImageInput?: boolean;
  /** Stable FK to `model_configuration.id`. Null for locally-constructed (non-persisted) configs. */
  modelConfigId: number | null;
}

export interface LLMOptionGroup {
  key: string;
  displayName: string;
  options: LLMOption[];
  Icon: IconFunctionComponent;
}

export function buildLlmOptions(
  llmProviders: LLMProviderDescriptor[] | undefined,
  currentModelName?: string
): LLMOption[] {
  if (!llmProviders) return [];

  const seenKeys = new Set<string>();
  const options: LLMOption[] = [];

  llmProviders.forEach((llmProvider) => {
    llmProvider.model_configurations
      .filter((mc) => mc.is_visible || mc.name === currentModelName)
      .forEach((mc) => {
        const key = `${llmProvider.provider}:${mc.name}`;
        if (seenKeys.has(key)) return;
        seenKeys.add(key);

        options.push({
          name: llmProvider.name ?? "",
          provider: llmProvider.provider,
          providerDisplayName:
            llmProvider.provider_display_name || llmProvider.provider,
          modelName: mc.name,
          modelConfigurationId: mc.id ?? null,
          displayName: mc.display_name || mc.name,
          vendor: mc.vendor || null,
          maxInputTokens: mc.max_input_tokens,
          region: mc.region || null,
          version: mc.version || null,
          supportsReasoning: mc.supports_reasoning || false,
          supportsImageInput: mc.supports_image_input || false,
          modelConfigId: mc.id ?? null,
        });
      });
  });

  return options;
}

export function groupLlmOptions(
  filteredOptions: LLMOption[]
): LLMOptionGroup[] {
  const groups = new Map<string, Omit<LLMOptionGroup, "key">>();

  filteredOptions.forEach((option) => {
    const provider = option.provider.toLowerCase();
    const isAggregator = AGGREGATOR_PROVIDERS.has(provider);
    const groupKey =
      isAggregator && option.vendor
        ? `${provider}/${option.vendor.toLowerCase()}`
        : provider;

    if (!groups.has(groupKey)) {
      let displayName: string;
      if (isAggregator && option.vendor) {
        const vendorDisplayName =
          option.vendor.charAt(0).toUpperCase() + option.vendor.slice(1);
        displayName = `${option.providerDisplayName}/${vendorDisplayName}`;
      } else {
        displayName = option.providerDisplayName;
      }
      groups.set(groupKey, {
        displayName,
        options: [],
        Icon: getModelIcon(provider),
      });
    }

    groups.get(groupKey)!.options.push(option);
  });

  const sortedKeys = Array.from(groups.keys()).sort((a, b) =>
    groups.get(a)!.displayName.localeCompare(groups.get(b)!.displayName)
  );

  return sortedKeys.map((key) => ({
    key,
    ...groups.get(key)!,
  }));
}
