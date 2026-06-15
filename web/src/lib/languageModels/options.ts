import type { FunctionComponent } from "react";
import type { IconProps } from "@opal/types";
import { LLMProviderDescriptor } from "@/lib/languageModels/types";
import { getModelIcon, getProvider } from "@/lib/languageModels";
import { AGGREGATOR_PROVIDERS } from "@/lib/languageModels/svc";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

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
}

export interface LLMOptionGroup {
  key: string;
  displayName: string;
  options: LLMOption[];
  Icon: FunctionComponent<IconProps>;
}

/**
 * Sentinel option representing "no explicit model — use the global default."
 * Identified by modelConfigurationId === null and an empty modelName.
 * Callers that support this option (e.g. AgentEditorPage) pass it back via
 * onChange; the handler should treat modelConfigurationId === null as "clear."
 */
export const GLOBAL_DEFAULT_LLM_OPTION: LLMOption = {
  name: "",
  provider: "",
  providerDisplayName: "",
  modelName: "",
  modelConfigurationId: null,
  displayName: "Global Default",
  vendor: null,
};

// ---------------------------------------------------------------------------
// buildLlmOptions
// ---------------------------------------------------------------------------

/**
 * Flattens an array of provider descriptors into a deduplicated list of
 * selectable model options. Hidden models are excluded unless their name
 * matches `currentModelName` (so an already-selected hidden model still
 * appears in the list).
 */
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
        const key =
          mc.id != null ? `id:${mc.id}` : `${llmProvider.provider}:${mc.name}`;
        if (seenKeys.has(key)) return;
        seenKeys.add(key);

        options.push({
          name: llmProvider.name ?? "",
          provider: llmProvider.provider,
          providerDisplayName:
            llmProvider.name || getProvider(llmProvider.provider).productName,
          modelName: mc.name,
          modelConfigurationId: mc.id ?? null,
          displayName: mc.effectiveDisplayName,
          vendor: mc.vendor || null,
          maxInputTokens: mc.max_input_tokens,
          region: mc.region || null,
          version: mc.version || null,
          supportsReasoning: mc.supports_reasoning || false,
          supportsImageInput: mc.supports_image_input || false,
        });
      });
  });

  return options;
}

// ---------------------------------------------------------------------------
// groupLlmOptions
// ---------------------------------------------------------------------------

/**
 * Groups a flat list of model options by provider, treating aggregator
 * providers (e.g. Bedrock) as sub-grouped by vendor. Groups are sorted
 * alphabetically by display name.
 */
export function groupLlmOptions(
  filteredOptions: LLMOption[]
): LLMOptionGroup[] {
  const groups = new Map<string, Omit<LLMOptionGroup, "key">>();

  filteredOptions.forEach((option) => {
    const provider = option.provider.toLowerCase();
    const isAggregator = AGGREGATOR_PROVIDERS.has(provider);
    const instanceKey = (
      option.name || option.providerDisplayName
    ).toLowerCase();
    const groupKey =
      isAggregator && option.vendor
        ? `${instanceKey}/${option.vendor.toLowerCase()}`
        : instanceKey;

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

// ---------------------------------------------------------------------------
// findModelConfigId
// ---------------------------------------------------------------------------

/**
 * Resolves a `{ provider, modelName }` pair to its `model_configuration_id`,
 * or `null` if not found. Used at callsites where the current selection is
 * tracked as a descriptor rather than a stable ID.
 */
export function findModelConfigId(
  llmProviders: LLMProviderDescriptor[] | undefined,
  provider: string,
  modelName: string
): number | null {
  if (!llmProviders) return null;
  for (const p of llmProviders) {
    if (p.provider !== provider) continue;
    const mc = p.model_configurations.find((m) => m.name === modelName);
    if (mc?.id != null) return mc.id;
  }
  return null;
}
