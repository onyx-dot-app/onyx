import {
  OnboardingState,
  OnboardingAction,
  OnboardingActionType,
  OnboardingStep,
} from "@/lib/onboarding/types";
import { STEP_NAVIGATION, STEP_CONFIG, TOTAL_STEPS } from "./constants";

export const initialState: OnboardingState = {
  currentStep: OnboardingStep.PreStep,
  stepIndex: 0,
  totalSteps: TOTAL_STEPS,
  data: {},
  isButtonActive: true,
  isLoading: false,
};

// Steps that ask nothing of the user, so their button is always active.
function asksNothing(step: OnboardingStep): boolean {
  return (
    step === OnboardingStep.OptionalSetup || step === OnboardingStep.PostStep
  );
}

export function onboardingReducer(
  state: OnboardingState,
  action: OnboardingAction
): OnboardingState {
  switch (action.type) {
    case OnboardingActionType.NEXT_STEP: {
      const nextStep = STEP_NAVIGATION[state.currentStep].next;
      if (!nextStep) return state;
      return {
        ...state,
        currentStep: nextStep,
        stepIndex: STEP_CONFIG[nextStep].index,
        isButtonActive: asksNothing(nextStep) ? true : state.isButtonActive,
        error: undefined,
      };
    }

    case OnboardingActionType.PREV_STEP: {
      const prevStep = STEP_NAVIGATION[state.currentStep].prev;
      if (!prevStep) return state;

      return {
        ...state,
        currentStep: prevStep,
        stepIndex: STEP_CONFIG[prevStep].index,
        error: undefined,
      };
    }

    case OnboardingActionType.GO_TO_STEP:
      return {
        ...state,
        currentStep: action.step,
        stepIndex: STEP_CONFIG[action.step].index,
        isButtonActive: asksNothing(action.step) ? true : state.isButtonActive,
        error: undefined,
      };

    case OnboardingActionType.UPDATE_DATA:
      return {
        ...state,
        data: { ...state.data, ...action.payload },
      };

    case OnboardingActionType.SET_BUTTON_ACTIVE:
      return {
        ...state,
        isButtonActive: action.isButtonActive,
      };

    case OnboardingActionType.SET_LOADING:
      return {
        ...state,
        isLoading: action.isLoading,
      };

    case OnboardingActionType.SET_ERROR:
      return {
        ...state,
        error: action.error,
      };

    case OnboardingActionType.RESET:
      return initialState;

    default:
      return state;
  }
}
