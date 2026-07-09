import type { LLMProviderDescriptor } from "@/lib/languageModels/types";

// Intro modal visibility
export type OnboardingModalMode =
  | { type: "initial-onboarding" } // First-visit intro
  | { type: "closed" }; // Modal not visible

export interface OnboardingModalController {
  mode: OnboardingModalMode;
  isOpen: boolean;

  // Intro actions
  close: () => void;
  completeOnboarding: () => Promise<void>;

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
