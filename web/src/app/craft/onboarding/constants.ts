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

// Tracks whether the user has dismissed the craft onboarding intro so it only
// auto-shows once per user (mirrors the main app's
// `onyx:onboardingCompleted:{userId}`).
function craftOnboardingSeenKey(userId: string): string {
  return `onyx:craftOnboardingSeen:${userId}`;
}

// localStorage access throws when the browser blocks site data; treat that
// as "not seen" rather than crashing the page.
export function getCraftOnboardingSeen(userId: string): boolean {
  if (typeof window === "undefined") return false;
  try {
    return (
      window.localStorage.getItem(craftOnboardingSeenKey(userId)) === "true"
    );
  } catch {
    return false;
  }
}

export function setCraftOnboardingSeen(userId: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(craftOnboardingSeenKey(userId), "true");
  } catch {
    // Storage unavailable — the intro will re-show next visit.
  }
}
