import { LLMProviderDescriptor } from "@/interfaces/llm";
import { getModelIcon } from "@/lib/languageModels";
import { AGGREGATOR_PROVIDERS } from "@/lib/languageModels/svc";
import { LLMOption, LLMOptionGroup } from "./interfaces";

/**
 * Build a flat list of LLM options from provider descriptors.
 * Pure utility — no React dependencies. Used by ModelSelector,
 * useMultiModelChat, ChatUI, and ModelPickerPopover.
 */
export function buildLlmOptions(
  llmProviders: LLMProviderDescriptor[] | undefined,
  currentModelName?: string
): LLMOption[] {
  if (!llmProviders) {
    return [];
  }

  // Track seen combinations of provider + exact model name to avoid true duplicates
  // (same model appearing from multiple LLM provider configs with same provider type)
  const seenKeys = new Set<string>();
  const options: LLMOption[] = [];

  llmProviders.forEach((llmProvider) => {
    llmProvider.model_configurations
      .filter(
        (modelConfiguration) =>
          modelConfiguration.is_visible ||
          modelConfiguration.name === currentModelName
      )
      .forEach((modelConfiguration) => {
        // Deduplicate by exact provider + model name combination
        const key = `${llmProvider.provider}:${modelConfiguration.name}`;
        if (seenKeys.has(key)) {
          return;
        }
        seenKeys.add(key);

        options.push({
          name: llmProvider.name ?? "",
          provider: llmProvider.provider,
          providerDisplayName:
            llmProvider.provider_display_name || llmProvider.provider,
          modelName: modelConfiguration.name,
          modelConfigurationId: modelConfiguration.id ?? null,
          displayName:
            modelConfiguration.display_name || modelConfiguration.name,
          vendor: modelConfiguration.vendor || null,
          maxInputTokens: modelConfiguration.max_input_tokens,
          region: modelConfiguration.region || null,
          version: modelConfiguration.version || null,
          supportsReasoning: modelConfiguration.supports_reasoning || false,
          supportsImageInput: modelConfiguration.supports_image_input || false,
          modelConfigId: modelConfiguration.id ?? null,
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

  return sortedKeys.map((key) => {
    const group = groups.get(key)!;
    return {
      key,
      displayName: group.displayName,
      options: group.options,
      Icon: group.Icon,
    };
  });
}
