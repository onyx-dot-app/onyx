// =============================================================================
// LLM Selection Types and Utilities
// =============================================================================

import { ModelConfiguration } from "@/lib/languageModels/types";

export interface BuildLlmSelection {
  providerName: string; // LLMProviderDescriptor.name (any configured provider)
  provider: string; // e.g., "anthropic"
  modelName: string; // e.g., "claude-opus-4-7"
}

export type ProviderKey = "anthropic" | "openai" | "openrouter";

// Craft-supported provider types (mirrors backend BUILD_MODE_ALLOWED_PROVIDER_TYPES)
// in priority order, plus the api-key placeholder for onboarding. Which model is
// recommended comes from the backend `is_recommended_default` flag on each model.
export const CRAFT_PROVIDERS: {
  key: ProviderKey;
  apiKeyPlaceholder: string;
  recommended?: boolean;
}[] = [
  { key: "anthropic", apiKeyPlaceholder: "sk-ant-...", recommended: true },
  { key: "openai", apiKeyPlaceholder: "sk-..." },
  { key: "openrouter", apiKeyPlaceholder: "sk-or-..." },
];

const CRAFT_PROVIDER_KEYS = new Set<string>(CRAFT_PROVIDERS.map((p) => p.key));

interface MinimalLlmProvider {
  name: string | null;
  provider: string;
  model_configurations: ModelConfiguration[];
}

export function isSupportedProviderType(provider: string): boolean {
  return CRAFT_PROVIDER_KEYS.has(provider);
}

export function hasSupportedCraftProvider(
  llmProviders: { provider: string }[] | undefined
): boolean {
  return !!llmProviders?.some((p) => isSupportedProviderType(p.provider));
}

// The Craft-recommended model name for a provider's model list (the one the
// backend flagged), falling back to the first visible model.
export function craftModelName(models: ModelConfiguration[]): string | null {
  return (
    models.find((m) => m.is_recommended_default)?.name ??
    models.find((m) => m.is_visible)?.name ??
    null
  );
}

// Highest-priority configured craft provider, with its recommended model.
// Access control is enforced server-side at session create.
export function getDefaultLlmSelection(
  llmProviders: MinimalLlmProvider[] | undefined
): BuildLlmSelection | null {
  if (!llmProviders) return null;

  for (const { key } of CRAFT_PROVIDERS) {
    const match = llmProviders.find((p) => p.provider === key);
    if (match) {
      const modelName = craftModelName(match.model_configurations);
      if (!modelName) continue;
      return {
        providerName: match.name ?? "",
        provider: match.provider,
        modelName,
      };
    }
  }

  return null;
}

// =============================================================================
// Onboarding "seen" flag
// =============================================================================

// Tracks whether the user has dismissed the craft onboarding modal so the
// intro only auto-shows once.
const CRAFT_ONBOARDING_SEEN_COOKIE_NAME = "craft_onboarding_seen";

export function getCraftOnboardingSeen(): boolean {
  if (typeof document === "undefined") return false;
  return document.cookie
    .split("; ")
    .some((row) => row.startsWith(`${CRAFT_ONBOARDING_SEEN_COOKIE_NAME}=`));
}

export function setCraftOnboardingSeen(): void {
  if (typeof document === "undefined") return;
  const expires = new Date(
    Date.now() + 365 * 24 * 60 * 60 * 1000
  ).toUTCString();
  document.cookie = `${CRAFT_ONBOARDING_SEEN_COOKIE_NAME}=1; path=/; expires=${expires}; SameSite=Lax`;
}
