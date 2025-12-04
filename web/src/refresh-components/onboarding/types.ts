import { IconProps } from "@/icons";

export enum OnboardingStep {
  Welcome = "welcome",
  Name = "name",
  LlmSetup = "llm-setup",
  Complete = "complete",
}

export interface OnboardingData {
  userName?: string;
  llmProviders?: string[];
  llmApiKey?: string;
}

export interface OnboardingState {
  currentStep: OnboardingStep;
  stepIndex: number;
  totalSteps: number;
  data: OnboardingData;
  isButtonActive: boolean;
  isLoading?: boolean;
  error?: string;
}

export enum OnboardingActionType {
  NEXT_STEP = "NEXT_STEP",
  PREV_STEP = "PREV_STEP",
  GO_TO_STEP = "GO_TO_STEP",
  UPDATE_DATA = "UPDATE_DATA",
  SET_BUTTON_ACTIVE = "SET_BUTTON_ACTIVE",
  SET_LOADING = "SET_LOADING",
  SET_ERROR = "SET_ERROR",
  RESET = "RESET",
}

export type OnboardingAction =
  | { type: OnboardingActionType.NEXT_STEP }
  | { type: OnboardingActionType.PREV_STEP }
  | { type: OnboardingActionType.GO_TO_STEP; step: OnboardingStep }
  | { type: OnboardingActionType.UPDATE_DATA; payload: Partial<OnboardingData> }
  | { type: OnboardingActionType.SET_BUTTON_ACTIVE; isButtonActive: boolean }
  | { type: OnboardingActionType.SET_LOADING; isLoading: boolean }
  | { type: OnboardingActionType.SET_ERROR; error: string | undefined }
  | { type: OnboardingActionType.RESET };

export type FinalStepItemProps = {
  title: string;
  description: string;
  icon: React.FunctionComponent<IconProps>;
  buttonText: string;
  buttonHref: string;
};

export type OnboardingActions = {
  nextStep: () => void;
  prevStep: () => void;
  goToStep: (step: OnboardingStep) => void;
  setButtonActive: (active: boolean) => void;
  updateName: (name: string) => void;
  updateData: (data: Partial<OnboardingData>) => void;
  setLoading: (isLoading: boolean) => void;
  setError: (error: string | undefined) => void;
  reset: () => void;
};
