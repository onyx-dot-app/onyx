// =============================================================================
// LLM Selection Types and Utilities
// =============================================================================

export interface BuildLlmSelection {
  providerName: string; // LLMProviderDescriptor.name (any configured provider)
  provider: string; // e.g., "anthropic"
  modelName: string; // e.g., "claude-opus-4-7"
}

export type ProviderKey = "anthropic" | "openai" | "openrouter";

// Single source of truth for Craft providers/models; everything below derives
// from it (allowed types, recommended flags, default selection).
export interface BuildModeModel {
  name: string;
  label: string;
  recommended?: boolean;
}

export interface BuildModeProvider {
  key: ProviderKey;
  label: string;
  providerName: string;
  recommended?: boolean;
  models: BuildModeModel[];
  // API-related fields (optional, only needed for onboarding modal)
  apiKeyPlaceholder?: string;
  apiKeyUrl?: string;
  apiKeyLabel?: string;
}

export const BUILD_MODE_PROVIDERS: BuildModeProvider[] = [
  {
    key: "anthropic",
    label: "Anthropic",
    providerName: "anthropic",
    recommended: true,
    models: [
      { name: "claude-opus-4-8", label: "Claude Opus 4.8", recommended: true },
      { name: "claude-opus-4-7", label: "Claude Opus 4.7" },
      { name: "claude-sonnet-4-6", label: "Claude Sonnet 4.6" },
    ],
    apiKeyPlaceholder: "sk-ant-...",
    apiKeyUrl: "https://console.anthropic.com/dashboard",
    apiKeyLabel: "Anthropic Console",
  },
  {
    key: "openai",
    label: "OpenAI",
    providerName: "openai",
    models: [
      { name: "gpt-5.5", label: "GPT-5.5", recommended: true },
      { name: "gpt-5.4", label: "GPT-5.4" },
      { name: "gpt-5.3", label: "GPT-5.3" },
    ],
    apiKeyPlaceholder: "sk-...",
    apiKeyUrl: "https://platform.openai.com/api-keys",
    apiKeyLabel: "OpenAI Dashboard",
  },
  {
    key: "openrouter",
    label: "OpenRouter",
    providerName: "openrouter",
    models: [
      {
        name: "minimax/minimax-m3",
        label: "MiniMax M3",
        recommended: true,
      },
      {
        name: "moonshotai/kimi-k2.6",
        label: "Kimi K2.6",
      },
    ],
    apiKeyPlaceholder: "sk-or-...",
    apiKeyUrl: "https://openrouter.ai/keys",
    apiKeyLabel: "OpenRouter Dashboard",
  },
];

// Allowed provider types are just the curated providers' keys. Keep
// BUILD_MODE_PROVIDERS in sync with the backend BUILD_MODE_ALLOWED_PROVIDER_TYPES
// (enforced by test_build_mode_provider_types_sync.py).
const ALLOWED_PROVIDER_TYPES = new Set<string>(
  BUILD_MODE_PROVIDERS.map((p) => p.key)
);
const RECOMMENDED_MODEL_NAMES = new Set(
  BUILD_MODE_PROVIDERS.flatMap((p) =>
    p.models.filter((m) => m.recommended).map((m) => m.name)
  )
);

// Top recommended Craft model's label, derived so UI copy isn't hardcoded.
export const RECOMMENDED_CRAFT_MODEL_LABEL: string = (() => {
  const provider =
    BUILD_MODE_PROVIDERS.find((p) => p.recommended) ?? BUILD_MODE_PROVIDERS[0]!;
  const model =
    provider.models.find((m) => m.recommended) ?? provider.models[0]!;
  return model.label;
})();

interface MinimalLlmProvider {
  name: string | null;
  provider: string;
}

export function isSupportedProviderType(provider: string): boolean {
  return ALLOWED_PROVIDER_TYPES.has(provider);
}

// True when at least one configured provider is a supported Craft type
// (anthropic/openai/openrouter). The gate for both onboarding LLM setup and
// pre-provisioning — an unsupported-only setup (e.g. Azure) can't craft.
export function hasSupportedCraftProvider(
  llmProviders: { provider: string }[] | undefined
): boolean {
  return !!llmProviders?.some((p) => isSupportedProviderType(p.provider));
}

export function isRecommendedModel(modelName: string): boolean {
  return RECOMMENDED_MODEL_NAMES.has(modelName);
}

function defaultModelForType(key: ProviderKey): string {
  const p = BUILD_MODE_PROVIDERS.find((x) => x.key === key)!;
  return (p.models.find((m) => m.recommended) ?? p.models[0]!).name;
}

// Highest-priority configured provider of a supported type, with that type's
// recommended model. Access control is enforced server-side at session create.
export function getDefaultLlmSelection(
  llmProviders: MinimalLlmProvider[] | undefined
): BuildLlmSelection | null {
  if (!llmProviders || llmProviders.length === 0) return null;

  for (const p of BUILD_MODE_PROVIDERS) {
    const match = llmProviders.find((lp) => lp.provider === p.key);
    if (match) {
      return {
        providerName: match.name ?? "",
        provider: match.provider,
        modelName: defaultModelForType(p.key),
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
