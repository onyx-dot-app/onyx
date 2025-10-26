import { useReducer, useCallback } from "react";
import { onboardingReducer, initialState } from "./reducer";
import { OnboardingActionType, OnboardingData } from "./types";

export function useOnboardingState() {
  const [state, dispatch] = useReducer(onboardingReducer, initialState);

  const nextStep = useCallback(() => {
    dispatch({ type: OnboardingActionType.NEXT_STEP });
  }, []);

  const prevStep = useCallback(() => {
    dispatch({ type: OnboardingActionType.PREV_STEP });
  }, []);

  const updateData = useCallback((data: Partial<OnboardingData>) => {
    dispatch({ type: OnboardingActionType.UPDATE_DATA, payload: data });
  }, []);

  const setLoading = useCallback((isLoading: boolean) => {
    dispatch({ type: OnboardingActionType.SET_LOADING, isLoading });
  }, []);

  const setError = useCallback((error: string | undefined) => {
    dispatch({ type: OnboardingActionType.SET_ERROR, error });
  }, []);

  const reset = useCallback(() => {
    dispatch({ type: OnboardingActionType.RESET });
  }, []);

  return {
    state,
    actions: {
      nextStep,
      prevStep,
      updateData,
      setLoading,
      setError,
      reset,
    },
  };
}
