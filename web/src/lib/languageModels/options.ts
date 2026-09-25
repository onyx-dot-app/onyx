import type { FunctionComponent } from "react";
import type {
  SelectDivider,
  SelectOption,
  SelectOptions,
} from "@opal/components";
import type { IconProps } from "@opal/types";
import { getModelIcon, getProvider } from "@/lib/languageModels/utils";
import { AGGREGATOR_PROVIDERS } from "@/lib/languageModels/svc";
import type {
  LLMOption,
  LLMOptionGroup,
  LLMProviderDescriptor,
  ModelOptionProvider,
  ReasoningEffortOverride,
  FilterModelConfigurationsOptions,
} from "@/lib/languageModels/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

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
// llmOptionKey
// ---------------------------------------------------------------------------

/**
 * Stable identity key for a selectable model. Prefers the unique model
 * configuration id; the provider + model name fallback can collide when two
 * providers expose a model with the same name, so it is only used for
 * options that were never persisted (no id).
 */
export function llmOptionKey(option: {
  provider: string;
  modelName: string;
  modelConfigurationId?: number | null;
}): string {
  return option.modelConfigurationId != null
    ? `mc:${option.modelConfigurationId}`
    : `${option.provider}:${option.modelName}`;
}

// ---------------------------------------------------------------------------
// buildLlmOptions
// ---------------------------------------------------------------------------

/**
 * Flattens an array of provider descriptors into a deduplicated list of
 * selectable model options. Hidden models require an existing selection or
 * an explicit admin opt-in.
 */
export function buildLlmOptions(
  llmProviders: ModelOptionProvider[] | undefined,
  currentModelName?: string,
  includeHiddenModels = false
): LLMOption[] {
  if (!llmProviders) return [];

  const seenKeys = new Set<string>();
  const options: LLMOption[] = [];

  llmProviders.forEach((llmProvider) => {
    llmProvider.model_configurations
      .filter(
        (mc) =>
          includeHiddenModels || mc.is_visible || mc.name === currentModelName
      )
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
          supportedReasoningEfforts: mc.supported_reasoning_efforts,
          reasoningEffortMax: mc.reasoning_effort_max,
          reasoningEffortDefault: mc.reasoning_effort_default,
          temperatureDefault: mc.temperature_default,
          supportsImageInput: mc.supports_image_input || false,
        });
      });
  });

  return options;
}

// ---------------------------------------------------------------------------
// buildModelProviderLookup
// ---------------------------------------------------------------------------

/**
 * Model identifier → provider slug map for icon resolution. Indexes by both
 * raw model name ("gpt-4.1") and display name ("GPT-4.1") so it resolves for
 * both live streaming and history reload, where only one of the two is known.
 */
export function buildModelProviderLookup(
  llmProviders: LLMProviderDescriptor[] | undefined
): Map<string, string> {
  const map = new Map<string, string>();
  for (const opt of buildLlmOptions(llmProviders)) {
    map.set(opt.modelName, opt.provider);
    map.set(opt.displayName, opt.provider);
  }
  return map;
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
        // vendor arrives display-cased from the backend (e.g. "OpenAI", "xAI")
        displayName = `${option.providerDisplayName}/${option.vendor}`;
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

// ---------------------------------------------------------------------------
// findLlmOptionById
// ---------------------------------------------------------------------------

/** The option behind a `model_configuration_id`, hidden models included. */
export function findLlmOptionById(
  llmProviders: ModelOptionProvider[] | undefined,
  modelConfigurationId: number | null
): LLMOption | null {
  if (modelConfigurationId === null) return null;
  return (
    buildLlmOptions(llmProviders, undefined, true).find(
      (option) => option.modelConfigurationId === modelConfigurationId
    ) ?? null
  );
}

// ---------------------------------------------------------------------------
// filterModelConfigurations
// ---------------------------------------------------------------------------

/**
 * Trims each provider's model list for a picker, dropping providers left
 * empty. The pure counterpart of the chat picker's own filtering, for a
 * dumb select that renders whatever it is given.
 */
export function filterModelConfigurations<T extends ModelOptionProvider>(
  providers: T[],
  {
    visibleOnly = true,
    imageInput = false,
    keep = null,
  }: FilterModelConfigurationsOptions = {}
): T[] {
  return providers
    .map((provider) => ({
      ...provider,
      model_configurations: provider.model_configurations.filter(
        (mc) =>
          (keep !== null && mc.id === keep) ||
          ((!visibleOnly || mc.is_visible) &&
            (!imageInput || mc.supports_image_input))
      ),
    }))
    .filter((provider) => provider.model_configurations.length > 0);
}

// ---------------------------------------------------------------------------
// Model select options (SimpleModelSelector)
// ---------------------------------------------------------------------------

/** A model configuration id as an `InputSingleSelect` value; null is empty. */
export function toSelectValue(modelConfigurationId: number | null): string {
  return modelConfigurationId === null ? "" : String(modelConfigurationId);
}

/** The inverse of `toSelectValue`; empty and junk map to null. */
export function fromSelectValue(value: string): number | null {
  if (value === "") return null;
  const id = Number(value);
  return Number.isInteger(id) ? id : null;
}

export interface BuildModelSelectOptionsOptions {
  /**
   * Group models under a foldable divider per provider (aggregators split
   * per vendor, as the chat picker does). Off, or with a single group,
   * the rows come flat: a lone header says nothing, and an admin can hide
   * grouping workspace-wide. Defaults to true.
   */
  grouped?: boolean;
}

/**
 * Every model configuration given, as Opal options, each model a row with
 * its icon. Nothing is filtered here; callers trim the list first. A model
 * without a configuration id cannot be chosen by id, so it is left out.
 */
export function buildModelSelectOptions(
  providers: ModelOptionProvider[],
  { grouped = true }: BuildModelSelectOptionsOptions = {}
): SelectOptions {
  const dividers: SelectDivider[] = groupLlmOptions(
    buildLlmOptions(providers, undefined, true)
  )
    .map((group) => ({
      title: group.displayName,
      foldable: true,
      options: group.options.flatMap((option): SelectOption[] =>
        option.modelConfigurationId == null
          ? []
          : [
              {
                value: String(option.modelConfigurationId),
                title: option.displayName,
                icon: getModelIcon(option.provider, option.modelName),
              },
            ]
      ),
    }))
    .filter((divider) => divider.options.length > 0);
  if (grouped && dividers.length > 1) return dividers;
  return dividers.flatMap((divider) => divider.options);
}
