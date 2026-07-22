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

export const CRAFT_RECOMMENDED_MODEL_NAMES = new Set([
  "gpt-5.6-sol",
  "gpt-5.5",
  "claude-fable-5",
  "claude-opus-4-8",
  "moonshotai/kimi-k3",
  "z-ai/glm-5.2",
]);

export function craftRecommendedModels(
  models: ModelConfiguration[]
): ModelConfiguration[] {
  return models.filter(
    (model) => model.is_visible && CRAFT_RECOMMENDED_MODEL_NAMES.has(model.name)
  );
}

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
    const modelName = craftRecommendedModels(provider.model_configurations)[0]
      ?.name;
    if (!modelName) continue;
    return {
      providerId: provider.id,
      providerName: provider.name ?? "",
      provider: provider.provider,
      modelName,
    };
  }

  // Must mirror the backend's _select_gateway_default fallback so the picker
  // reflects the model a session would actually use.
  for (const provider of candidates) {
    const modelName = provider.model_configurations.find(
      (model) => model.is_visible
    )?.name;
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
