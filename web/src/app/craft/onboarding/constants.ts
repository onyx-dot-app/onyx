// =============================================================================
// LLM Selection Types and Utilities
// =============================================================================

import { ModelConfiguration } from "@/lib/languageModels/types";

export interface BuildLlmSelection {
  providerId: number;
  providerName: string; // LLMProviderDescriptor.name (any configured provider)
  provider: string; // e.g., "anthropic"
  modelName: string; // e.g., "claude-opus-4-7"
}

export type ProviderKey = "anthropic" | "openai" | "openrouter";

export const CRAFT_GATEWAY_PROVIDER = "onyx";

// The recommended model is each provider's `is_recommended_default`, sourced
// server-side from recommended-models.json — never a hardcoded list here.
export function isCraftRecommendedModel(model: ModelConfiguration): boolean {
  return model.is_visible && (model.is_recommended_default ?? false);
}

// Common providers sorted first in the onboarding catalog. Craft routes every
// provider through the gateway, so this is display ordering only, not a gate.
export const CRAFT_PROVIDERS: ProviderKey[] = [
  "anthropic",
  "openai",
  "openrouter",
];

const CRAFT_PROVIDER_KEYS = new Set<string>(CRAFT_PROVIDERS);

interface MinimalLlmProvider {
  id: number;
  name: string | null;
  provider: string;
  provider_display_name?: string | null;
  model_configurations: ModelConfiguration[];
}

export function craftProviderDisplayName(provider: {
  name: string | null;
  provider: string;
  provider_display_name?: string | null;
}): string {
  return provider.name || provider.provider_display_name || provider.provider;
}

export function isSupportedProviderType(provider: string): boolean {
  return CRAFT_PROVIDER_KEYS.has(provider);
}

export function hasSupportedCraftProvider(
  llmProviders:
    | { provider: string; model_configurations?: ModelConfiguration[] }[]
    | undefined
): boolean {
  return !!llmProviders?.some((provider) =>
    provider.model_configurations?.some((model) => model.is_visible)
  );
}

// Access control is enforced server-side at session create.
export function getDefaultLlmSelection(
  llmProviders: MinimalLlmProvider[] | undefined
): BuildLlmSelection | null {
  if (!llmProviders) return null;

  // Must match the backend's casefold-then-id ordering in
  // _gateway_provider_order; localeCompare would diverge.
  const candidates = [...llmProviders].sort((left, right) => {
    const leftName = craftProviderDisplayName(left).toLowerCase();
    const rightName = craftProviderDisplayName(right).toLowerCase();
    if (leftName !== rightName) return leftName < rightName ? -1 : 1;
    return left.id - right.id;
  });

  for (const provider of candidates) {
    const modelName = provider.model_configurations.find(
      isCraftRecommendedModel
    )?.name;
    if (!modelName) continue;
    return {
      providerId: provider.id,
      providerName: provider.name ?? "",
      provider: provider.provider,
      modelName,
    };
  }

  // Must mirror the backend's _select_gateway_default fallback so the picker
  // reflects the model a session would actually use: the first visible model
  // by sorted name (backend's _visible_models_by_name), not DB order.
  for (const provider of candidates) {
    const modelName = provider.model_configurations
      .filter((model) => model.is_visible)
      .map((model) => model.name)
      .sort()[0];
    if (!modelName) continue;
    return {
      providerId: provider.id,
      providerName: provider.name ?? "",
      provider: provider.provider,
      modelName,
    };
  }

  return null;
}

export function resolveSessionLlmSelection(
  agentProvider: string | null | undefined,
  agentModel: string | null | undefined,
  llmProviders: MinimalLlmProvider[] | undefined
): BuildLlmSelection | null {
  if (!agentProvider || !agentModel || !llmProviders) return null;

  const separatorIndex = agentModel.indexOf("/");
  const qualifiedProviderId = Number(agentModel.slice(0, separatorIndex));
  const isGatewayModel =
    agentProvider === CRAFT_GATEWAY_PROVIDER &&
    separatorIndex > 0 &&
    Number.isInteger(qualifiedProviderId);
  // Legacy sessions stored only the provider type; prefer a same-type
  // provider that actually hosts the model so the next turn's explicit
  // provider_id doesn't route to one that lacks it.
  const provider = isGatewayModel
    ? llmProviders.find((candidate) => candidate.id === qualifiedProviderId)
    : (llmProviders.find(
        (candidate) =>
          candidate.provider === agentProvider &&
          candidate.model_configurations.some(
            (model) => model.is_visible && model.name === agentModel
          )
      ) ??
      llmProviders.find((candidate) => candidate.provider === agentProvider));
  if (!provider) return null;
  const modelName = isGatewayModel
    ? agentModel.slice(separatorIndex + 1)
    : agentModel;
  if (
    isGatewayModel &&
    !provider.model_configurations.some(
      (model) => model.is_visible && model.name === modelName
    )
  ) {
    return null;
  }

  return {
    providerId: provider.id,
    providerName: provider.name ?? provider.provider,
    provider: provider.provider,
    modelName,
  };
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
