// Mirrors web languageModels/utils.ts + `getModelIcon`. Flatten providers →
// selectable options, group by provider, resolve the default model, and pick a
// provider icon.
import type { ComponentType } from "react";

import { SvgCpu } from "@/components/icons/SvgCpu";
import type { IconProps } from "@/components/icons/Icon";
import {
  AnthropicLogo,
  GoogleLogo,
  OllamaLogo,
  OpenaiLogo,
} from "@/components/ui/logos";
import type {
  DefaultModel,
  LLMOption,
  LLMProviderDescriptor,
  ModelConfiguration,
  SelectedModel,
} from "@/lib/types";

/** custom_display_name > display_name > name (web parity). */
export function modelDisplayName(m: ModelConfiguration): string {
  return m.custom_display_name || m.display_name || m.name;
}

/** Flatten every provider's *visible* model_configurations into selectable options. */
export function buildLlmOptions(
  providers: LLMProviderDescriptor[],
): LLMOption[] {
  const options: LLMOption[] = [];
  for (const p of providers) {
    for (const m of p.model_configurations) {
      if (!m.is_visible) continue;
      options.push({
        name: p.name ?? "",
        provider: p.provider,
        providerDisplayName: p.provider_display_name,
        modelName: m.name,
        displayName: modelDisplayName(m),
        vendor: m.vendor,
        supportsReasoning: m.supports_reasoning,
        supportsImageInput: m.supports_image_input,
      });
    }
  }
  return options;
}

export interface LLMOptionGroup {
  key: string;
  displayName: string;
  options: LLMOption[];
}

/**
 * Group options by provider — or by `provider/vendor` for aggregator providers
 * (e.g. Bedrock) so each underlying vendor reads as its own group. Sorted by name.
 */
export function groupLlmOptions(options: LLMOption[]): LLMOptionGroup[] {
  const groups = new Map<string, LLMOptionGroup>();
  for (const o of options) {
    const isAggregator =
      !!o.vendor && o.vendor.toLowerCase() !== o.provider.toLowerCase();
    const key = isAggregator ? `${o.provider}/${o.vendor}` : o.provider;
    const displayName = isAggregator
      ? (o.vendor as string)
      : o.providerDisplayName;
    let group = groups.get(key);
    if (!group) {
      group = { key, displayName, options: [] };
      groups.set(key, group);
    }
    group.options.push(o);
  }
  return Array.from(groups.values()).sort((a, b) =>
    a.displayName.localeCompare(b.displayName),
  );
}

// Substring matchers (provider kind → vendor → model name), mirroring web's
// MODEL_ICON_MAP. First match wins; unmatched models fall back to the Cpu glyph.
const ICON_MATCHERS: [string, ComponentType<IconProps>][] = [
  // Provider kind matches first (e.g. "ollama_chat" → Ollama, even for a gpt-* model).
  ["ollama", OllamaLogo],
  ["anthropic", AnthropicLogo],
  ["openai", OpenaiLogo],
  ["claude", AnthropicLogo],
  ["gemini", GoogleLogo],
  ["vertex", GoogleLogo],
  ["google", GoogleLogo],
  ["gpt", OpenaiLogo],
];

/**
 * Resolve a provider/model brand logo from the provider kind, optional vendor, and
 * model name (checked as lowercase substrings). Falls back to the generic `Cpu` icon.
 */
export function getModelIcon(
  provider: string,
  vendor?: string,
  modelName?: string,
): ComponentType<IconProps> {
  const haystacks = [provider, vendor, modelName]
    .filter((s): s is string => !!s)
    .map((s) => s.toLowerCase());
  for (const [key, Icon] of ICON_MATCHERS) {
    if (haystacks.some((h) => h.includes(key))) return Icon;
  }
  return SvgCpu;
}

/**
 * Pick the default model (mirror web `getFinalLLM`): start from the workspace
 * `default_text` pointer (or the first visible model), then let the persona's
 * `default_model_configuration_id` override it. Returns null when nothing is available.
 */
export function resolveDefaultModel(
  providers: LLMProviderDescriptor[],
  defaultText?: DefaultModel | null,
  personaDefaultModelConfigId?: number | null,
): SelectedModel | null {
  let base: { p: LLMProviderDescriptor; mc: ModelConfiguration } | null = null;

  // 1) Workspace default_text (provider_id + model_name).
  if (defaultText) {
    const p = providers.find((x) => x.id === defaultText.provider_id);
    const mc = p?.model_configurations.find(
      (m) => m.name === defaultText.model_name,
    );
    if (p && mc) base = { p, mc };
  }

  // 2) Fallback: first visible model of the first provider that has one.
  if (!base) {
    for (const p of providers) {
      const mc = p.model_configurations.find((m) => m.is_visible);
      if (mc) {
        base = { p, mc };
        break;
      }
    }
  }

  // 3) Persona default overrides, by model_configuration id.
  if (personaDefaultModelConfigId != null) {
    for (const p of providers) {
      const mc = p.model_configurations.find(
        (m) => m.id === personaDefaultModelConfigId,
      );
      if (mc) {
        base = { p, mc };
        break;
      }
    }
  }

  if (!base) return null;
  return {
    name: base.p.name ?? "",
    provider: base.p.provider,
    modelName: base.mc.name,
    displayName: modelDisplayName(base.mc),
  };
}

/** Find a model_configuration by name within a single provider's list. */
export function findModelInModelConfigurations(
  modelConfigurations: ModelConfiguration[],
  modelName: string,
): ModelConfiguration | null {
  return modelConfigurations.find((m) => m.name === modelName) || null;
}

/**
 * Locate a model_configuration across providers (web parity:
 * `findModelConfiguration`). When `providerName` is given, only that provider
 * instance is searched; otherwise the first match wins.
 */
export function findModelConfiguration(
  providers: LLMProviderDescriptor[],
  modelName: string,
  providerName: string | null = null,
): ModelConfiguration | null {
  if (providerName) {
    const provider = providers.find((p) => p.name === providerName);
    return provider
      ? findModelInModelConfigurations(provider.model_configurations, modelName)
      : null;
  }
  for (const provider of providers) {
    const mc = findModelInModelConfigurations(
      provider.model_configurations,
      modelName,
    );
    if (mc) return mc;
  }
  return null;
}

/**
 * Whether the given model accepts image input (web parity:
 * `modelSupportsImageInput`). Used to gate image attachments — when false, the
 * composer refuses image picks and prompts the user to switch to a vision model.
 */
export function modelSupportsImageInput(
  providers: LLMProviderDescriptor[],
  modelName: string,
  providerName: string | null = null,
): boolean {
  return (
    findModelConfiguration(providers, modelName, providerName)
      ?.supports_image_input || false
  );
}
