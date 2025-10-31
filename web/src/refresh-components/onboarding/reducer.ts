import {
  OnboardingState,
  OnboardingAction,
  OnboardingActionType,
  OnboardingStep,
} from "./types";
import { STEP_NAVIGATION, STEP_CONFIG, TOTAL_STEPS } from "./constants";

export const initialState: OnboardingState = {
  currentStep: OnboardingStep.Name,
  stepIndex: 1,
  totalSteps: TOTAL_STEPS,
  data: {},
  isButtonActive: false,
  isLoading: false,
};

export function onboardingReducer(
  state: OnboardingState,
  action: OnboardingAction
): OnboardingState {
  switch (action.type) {
    case OnboardingActionType.NEXT_STEP: {
      const nextStep = STEP_NAVIGATION[state.currentStep].next;
      if (!nextStep) return state;
      console.log("currentStep", state.currentStep);
      console.log("nextStep", nextStep);
      return {
        ...state,
        currentStep: nextStep,
        stepIndex: STEP_CONFIG[nextStep].index,
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
      console.log("goToStep", action.step, state.currentStep);
      return {
        ...state,
        currentStep: action.step,
        stepIndex: STEP_CONFIG[action.step].index,
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
