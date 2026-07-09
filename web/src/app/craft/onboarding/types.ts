import type {
  LLMProviderDescriptor,
  LLMProviderResponse,
} from "@/lib/languageModels/types";

// New mode-based modal types
export type OnboardingModalMode =
  | { type: "initial-onboarding" } // Full flow: page1 → llm-setup?
  | { type: "add-llm"; provider?: string } // Just llm-setup step
  | { type: "closed" }; // Modal not visible

export type OnboardingStep = "llm-setup" | "page1" | "page2";

export interface OnboardingModalController {
  mode: OnboardingModalMode;
  isOpen: boolean;

  // Actions
  openLlmSetup: (provider?: string) => void;
  close: () => void;

  // Data needed for modal
  llmProviders: LLMProviderDescriptor[] | undefined;

  // State
  isAdmin: boolean;
  hasAnyProvider: boolean; // A configured provider exposes a supported model
  isLoading: boolean; // True while LLM providers are loading

  // Callbacks
  completeOnboarding: () => Promise<void>;
  completeLlmSetup: () => Promise<void>;
  refetchLlmProviders: () => Promise<
    LLMProviderResponse<LLMProviderDescriptor> | undefined
  >;
}
