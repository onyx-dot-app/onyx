// =============================================================================
// LLM Selection Types and Utilities
// =============================================================================

export interface BuildLlmSelection {
  providerName: string; // e.g., "build-mode-anthropic" (LLMProviderDescriptor.name)
  provider: string; // e.g., "anthropic"
  modelName: string; // e.g., "claude-opus-4-5"
}

// Recommended models config
export const RECOMMENDED_BUILD_MODELS = {
  preferred: {
    provider: "anthropic",
    modelName: "claude-opus-4-5",
    displayName: "Claude Opus 4.5",
  },
  alternatives: [{ provider: "anthropic", modelName: "claude-sonnet-4-5" }],
} as const;

// Cookie utilities
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
  // Cookie expires in 1 year
  const expires = new Date(
    Date.now() + 365 * 24 * 60 * 60 * 1000
  ).toUTCString();
  document.cookie = `${BUILD_LLM_COOKIE_KEY}=${value}; path=/; expires=${expires}; SameSite=Lax`;
}

export function clearBuildLlmSelection(): void {
  if (typeof document === "undefined") return;
  document.cookie = `${BUILD_LLM_COOKIE_KEY}=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT`;
}

export function isRecommendedModel(
  provider: string,
  modelName: string
): boolean {
  const { preferred, alternatives } = RECOMMENDED_BUILD_MODELS;
  // Exact match for preferred model
  if (preferred.provider === provider && modelName === preferred.modelName) {
    return true;
  }
  // Exact match for alternatives
  return alternatives.some(
    (alt) => alt.provider === provider && modelName === alt.modelName
  );
}

// Curated providers for Build mode (shared between BuildOnboardingModal and BuildLLMPopover)
export interface BuildModeModel {
  name: string;
  label: string;
  recommended?: boolean;
}

export interface BuildModeProvider {
  key: string;
  label: string;
  providerName: string;
  recommended?: boolean;
  models: BuildModeModel[];
}

export const BUILD_MODE_PROVIDERS: BuildModeProvider[] = [
  {
    key: "anthropic",
    label: "Anthropic",
    providerName: "anthropic",
    recommended: true,
    models: [
      { name: "claude-opus-4-5", label: "Claude Opus 4.5", recommended: true },
      { name: "claude-sonnet-4-5", label: "Claude Sonnet 4.5" },
    ],
  },
  {
    key: "openai",
    label: "OpenAI",
    providerName: "openai",
    models: [
      { name: "gpt-5.2", label: "GPT-5.2", recommended: true },
      { name: "gpt-5.1", label: "GPT-5.1" },
    ],
  },
  {
    key: "openrouter",
    label: "OpenRouter",
    providerName: "openrouter",
    models: [
      {
        name: "moonshotai/kimi-k2-thinking",
        label: "Kimi K2 Thinking",
        recommended: true,
      },
      { name: "google/gemini-3-pro-preview", label: "Gemini 3 Pro" },
      { name: "qwen/qwen3-235b-a22b-thinking-2507", label: "Qwen3 235B" },
    ],
  },
];

// =============================================================================
// User Info/Persona Constants
// =============================================================================

export const WORK_AREA_OPTIONS = [
  { value: "engineering", label: "Engineering" },
  { value: "product", label: "Product" },
  { value: "executive", label: "Executive" },
  { value: "sales", label: "Sales" },
  { value: "marketing", label: "Marketing" },
  { value: "other", label: "Other" },
];

export const LEVEL_OPTIONS = [
  { value: "ic", label: "IC" },
  { value: "manager", label: "Manager" },
];

export const WORK_AREAS_WITH_LEVEL = ["engineering", "product", "sales"];

export const BUILD_USER_PERSONA_COOKIE_NAME = "build_user_persona";

// Helper type for the consolidated cookie
export interface BuildUserPersona {
  workArea: string;
  level?: string;
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
    return JSON.parse(decodeURIComponent(cookieValue));
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
