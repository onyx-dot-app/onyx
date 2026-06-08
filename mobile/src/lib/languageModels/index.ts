// Mirrors web languageModels/utils.ts + `getModelIcon`.
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

// custom_display_name > display_name > name (web parity).
export function modelDisplayName(m: ModelConfiguration): string {
  return m.custom_display_name || m.display_name || m.name;
}

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

// Aggregator providers (e.g. Bedrock) group by `provider/vendor` so each
// underlying vendor reads as its own group.
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

// Mirrors web's MODEL_ICON_MAP. First match wins; ordering matters so the
// provider kind matches before the model name (e.g. "ollama_chat" with a gpt-*
// model → Ollama, not OpenAI).
const ICON_MATCHERS: [string, ComponentType<IconProps>][] = [
  ["ollama", OllamaLogo],
  ["anthropic", AnthropicLogo],
  ["openai", OpenaiLogo],
  ["claude", AnthropicLogo],
  ["gemini", GoogleLogo],
  ["vertex", GoogleLogo],
  ["google", GoogleLogo],
  ["gpt", OpenaiLogo],
];

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

// Mirrors web `getFinalLLM`: workspace default, else first visible model, then
// persona override.
export function resolveDefaultModel(
  providers: LLMProviderDescriptor[],
  defaultText?: DefaultModel | null,
  personaDefaultModelConfigId?: number | null,
): SelectedModel | null {
  let base: { p: LLMProviderDescriptor; mc: ModelConfiguration } | null = null;

  if (defaultText) {
    const p = providers.find((x) => x.id === defaultText.provider_id);
    const mc = p?.model_configurations.find(
      (m) => m.name === defaultText.model_name,
    );
    if (p && mc) base = { p, mc };
  }

  if (!base) {
    for (const p of providers) {
      const mc = p.model_configurations.find((m) => m.is_visible);
      if (mc) {
        base = { p, mc };
        break;
      }
    }
  }

  // Persona default overrides the workspace/fallback choice, by config id.
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

export function findModelInModelConfigurations(
  modelConfigurations: ModelConfiguration[],
  modelName: string,
): ModelConfiguration | null {
  return modelConfigurations.find((m) => m.name === modelName) || null;
}

// `providerName` scopes the search to that provider; otherwise first match wins.
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

// Gates image attachments — when false the composer refuses image picks.
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
