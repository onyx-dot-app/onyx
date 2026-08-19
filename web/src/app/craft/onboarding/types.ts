import type { LLMProviderDescriptor } from "@/lib/languageModels/types";

export interface OnboardingModalController {
  // Intro tour
  introOpen: boolean;
  /** Explicit finish (final CTA): marks seen, tracks completion, closes. */
  completeOnboarding: () => void;
  /** Bail-out (Escape / X): marks seen and closes without tracking. */
  dismissOnboarding: () => void;

  // Shared provider-setup modal (any well-known provider type)
  activeProviderKey: string | null;
  openProviderModal: (providerKey: string) => void;
  closeProviderModal: () => void;

  // Data needed for gating
  llmProviders: LLMProviderDescriptor[] | undefined;
  isAdmin: boolean;
  hasAnyProvider: boolean; // A configured provider exposes a supported model
  isLoading: boolean; // True while LLM providers are loading
}
