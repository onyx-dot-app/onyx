import { WorkArea, Level } from "./constants";
import type {
  LLMProviderDescriptor,
  LLMProviderResponse,
} from "@/lib/languageModels/types";

export interface BuildUserInfo {
  firstName: string;
  lastName?: string;
  workArea: WorkArea;
  level?: Level;
}

// New mode-based modal types
export type OnboardingModalMode =
  | { type: "initial-onboarding" } // Full flow: page1 → llm-setup? → user-info
  | { type: "edit-user-info" } // Just user-info step
  | { type: "add-llm"; provider?: string } // Just llm-setup step
  | { type: "closed" }; // Modal not visible

export type OnboardingStep = "user-info" | "llm-setup" | "page1" | "page2";

export interface OnboardingModalController {
  mode: OnboardingModalMode;
  isOpen: boolean;

  // Actions
  openUserInfoEditor: () => void;
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
  hasUserInfo: boolean; // User has completed user-info (workArea set)
  hasAnyProvider: boolean; // A configured provider exposes a supported model
  isLoading: boolean; // True while LLM providers are loading

  // Callbacks
  completeUserInfo: (info: BuildUserInfo) => Promise<void>;
  completeLlmSetup: () => Promise<void>;
  refetchLlmProviders: () => Promise<
    LLMProviderResponse<LLMProviderDescriptor> | undefined
  >;
}
