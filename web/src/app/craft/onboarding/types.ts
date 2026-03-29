import { WorkArea, Level } from "./constants";

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
  | { type: "initial-onboarding" } // Full flow: page1 → user-info
  | { type: "edit-persona" } // Just user-info step
  | { type: "closed" }; // Modal not visible

export type OnboardingStep = "user-info" | "page1" | "page2";

export interface OnboardingModalController {
  mode: OnboardingModalMode;
  isOpen: boolean;

  // Actions
  openPersonaEditor: () => void;
  close: () => void;

  // Data needed for modal
  initialValues: {
    firstName: string;
    lastName: string;
    workArea: WorkArea | undefined;
    level: Level | undefined;
  };

  // State
  isAdmin: boolean;
  hasUserInfo: boolean; // User has completed user-info (name + workArea)
  isLoading: boolean; // True while LLM providers are loading

  // Callbacks
  completeUserInfo: (info: BuildUserInfo) => Promise<void>;
}
