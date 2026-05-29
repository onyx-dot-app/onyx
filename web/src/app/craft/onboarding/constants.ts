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
      { name: "claude-opus-4-7", label: "Claude Opus 4.7", recommended: true },
      { name: "claude-opus-4-6", label: "Claude Opus 4.6" },
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
        name: "moonshotai/kimi-k2.6",
        label: "Kimi K2.6",
        recommended: true,
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

interface MinimalLlmProvider {
  name: string | null;
  provider: string;
}

export function isSupportedProviderType(provider: string): boolean {
  return ALLOWED_PROVIDER_TYPES.has(provider);
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

const BUILD_LLM_COOKIE_KEY = "build_llm_selection";

export function getBuildLlmSelection(): BuildLlmSelection | null {
  if (typeof document === "undefined") return null;
  const cookie = document.cookie
    .split("; ")
    .find((row) => row.startsWith(`${BUILD_LLM_COOKIE_KEY}=`));
  if (!cookie) return null;
  try {
    const value = cookie.split("=")[1];
    if (!value) return null;
    return JSON.parse(decodeURIComponent(value));
  } catch {
    return null;
  }
}

export function setBuildLlmSelection(selection: BuildLlmSelection): void {
  if (typeof document === "undefined") return;
  const value = encodeURIComponent(JSON.stringify(selection));
  const expires = new Date(
    Date.now() + 365 * 24 * 60 * 60 * 1000
  ).toUTCString();
  document.cookie = `${BUILD_LLM_COOKIE_KEY}=${value}; path=/; expires=${expires}; SameSite=Lax`;
}

export function clearBuildLlmSelection(): void {
  if (typeof document === "undefined") return;
  document.cookie = `${BUILD_LLM_COOKIE_KEY}=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT`;
}

// =============================================================================
// User Info Constants
// =============================================================================

export enum WorkArea {
  ENGINEERING = "engineering",
  PRODUCT = "product",
  EXECUTIVE = "executive",
  SALES = "sales",
  MARKETING = "marketing",
  OTHER = "other",
}

export enum Level {
  IC = "ic",
  MANAGER = "manager",
}

// Helper to capitalize first letter
const capitalize = (str: string): string => {
  return str.charAt(0).toUpperCase() + str.slice(1);
};

// Derive WORK_AREA_OPTIONS from WorkArea enum
export const WORK_AREA_OPTIONS = Object.values(WorkArea).map((value) => ({
  value,
  label: capitalize(value),
}));

// Derive LEVEL_OPTIONS from Level enum
export const LEVEL_OPTIONS = Object.values(Level).map((value) => ({
  value,
  label: value === Level.IC ? "IC" : capitalize(value),
}));

// Work areas where level selection is required
// Executive has the same persona for both levels, so level is optional
export const WORK_AREAS_REQUIRING_LEVEL: WorkArea[] = [
  WorkArea.ENGINEERING,
  WorkArea.PRODUCT,
  WorkArea.SALES,
  WorkArea.MARKETING,
  WorkArea.OTHER,
];

export const BUILD_USER_PERSONA_COOKIE_NAME = "build_user_persona";

// Helper type for the consolidated cookie
export interface BuildUserPersona {
  workArea: WorkArea;
  level?: Level;
}

// Helper functions for getting/setting the consolidated cookie
export function getBuildUserPersona(): BuildUserPersona | null {
  if (typeof window === "undefined") return null;

  const cookieValue = document.cookie
    .split("; ")
    .find((row) => row.startsWith(`${BUILD_USER_PERSONA_COOKIE_NAME}=`))
    ?.split("=")[1];

  if (!cookieValue) return null;

  try {
    const parsed = JSON.parse(decodeURIComponent(cookieValue));
    // Validate and cast to enum types
    if (
      parsed.workArea &&
      Object.values(WorkArea).includes(parsed.workArea as WorkArea)
    ) {
      return {
        workArea: parsed.workArea as WorkArea,
        level:
          parsed.level && Object.values(Level).includes(parsed.level as Level)
            ? (parsed.level as Level)
            : undefined,
      };
    }
    return null;
  } catch {
    return null;
  }
}

export function setBuildUserPersona(persona: BuildUserPersona): void {
  const cookieValue = encodeURIComponent(JSON.stringify(persona));
  const expires = new Date();
  expires.setFullYear(expires.getFullYear() + 1);
  document.cookie = `${BUILD_USER_PERSONA_COOKIE_NAME}=${cookieValue}; path=/; expires=${expires.toUTCString()}`;
}
