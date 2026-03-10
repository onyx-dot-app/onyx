import { WorkArea, Level } from "./constants";
import type {
  LLMProviderDescriptor,
  LLMProviderResponse,
} from "@/interfaces/llm";

export interface BuildUserInfo {
  firstName: string;
  lastName?: string;
  workArea: WorkArea;
  level?: Level;
}

// Legacy flow interface (kept for backwards compatibility during migration)
export interface BuildOnboardingFlow {
  showNotAllowedModal: boolean;
  showUserInfoModal: boolean;
  showLlmModal: boolean;
}

// New mode-based modal types
export type OnboardingModalMode =
  | { type: "initial-onboarding" } // Full flow: user-info → llm? → content
  | { type: "edit-persona" } // Just user-info step
  | { type: "add-llm"; provider?: string } // Just llm-setup step
  | { type: "closed" }; // Modal not visible

export type OnboardingStep = "user-info" | "llm-setup" | "page1" | "page2";

export interface OnboardingModalController {
  mode: OnboardingModalMode;
  isOpen: boolean;

  // Actions
  openPersonaEditor: () => void;
  openLlmSetup: (provider?: string) => void;
  close: () => void;

  // Data needed for modal
  llmProviders: LLMProviderDescriptor[] | undefined;
  initialValues: {
    firstName: string;
    lastName: string;
    workArea: WorkArea | undefined;
    level: Level | undefined;
  };

  // State
  isAdmin: boolean;
  hasUserInfo: boolean; // User has completed user-info (name + workArea)
  allProvidersConfigured: boolean; // All 3 providers (anthropic, openai, openrouter) are configured
  hasAnyProvider: boolean; // At least 1 provider is configured (allows skipping)
  isLoading: boolean; // True while LLM providers are loading

  // Callbacks
  completeUserInfo: (info: BuildUserInfo) => Promise<void>;
  completeLlmSetup: () => Promise<void>;
  refetchLlmProviders: () => Promise<
    LLMProviderResponse<LLMProviderDescriptor> | undefined
  >;
}
