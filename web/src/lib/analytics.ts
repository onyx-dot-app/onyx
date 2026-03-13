import posthog from "posthog-js";

export enum LLMProviderConfiguredSource {
  ADMIN_PAGE = "admin_page",
  CHAT_ONBOARDING = "chat_onboarding",
  CRAFT_ONBOARDING = "craft_onboarding",
}

interface LLMProviderConfiguredProperties {
  provider: string;
  is_creation: boolean;
  source: LLMProviderConfiguredSource;
}

export function trackLLMProviderConfigured(
  properties: LLMProviderConfiguredProperties
): void {
  posthog.capture("configured_llm_provider", properties);
}
