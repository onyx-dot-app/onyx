import { useReducer, useCallback, useState, useEffect } from "react";
import { onboardingReducer, initialState } from "./reducer";
import {
  OnboardingActions,
  OnboardingActionType,
  OnboardingData,
  OnboardingState,
} from "./types";
import { WellKnownLLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";

export function useOnboardingState(): {
  state: OnboardingState;
  llmDescriptors: WellKnownLLMProviderDescriptor[];
  actions: OnboardingActions;
} {
  const [state, dispatch] = useReducer(onboardingReducer, initialState);
  const [llmDescriptors, setLlmDescriptors] = useState<
    WellKnownLLMProviderDescriptor[]
  >([]);

  useEffect(() => {
    const fetchLlmDescriptors = async () => {
      try {
        const response = await fetch("/api/admin/llm/built-in/options");
        if (!response.ok) {
          setLlmDescriptors([]);
          return;
        }
        const data = await response.json();
        setLlmDescriptors(Array.isArray(data) ? data : []);
      } catch (_e) {
        setLlmDescriptors([]);
      }
    };
    fetchLlmDescriptors();
  }, []);

  const nextStep = useCallback(() => {
    dispatch({ type: OnboardingActionType.NEXT_STEP });
  }, []);

  const prevStep = useCallback(() => {
    dispatch({ type: OnboardingActionType.PREV_STEP });
  }, []);

  const updateName = useCallback((name: string) => {
    dispatch({
      type: OnboardingActionType.UPDATE_DATA,
      payload: { userName: name },
    });
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
    llmDescriptors,
    actions: {
      nextStep,
      prevStep,
      updateName,
      updateData,
      setLoading,
      setError,
      reset,
    },
  };
}
