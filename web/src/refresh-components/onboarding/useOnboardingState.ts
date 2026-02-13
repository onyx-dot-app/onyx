import { useReducer, useCallback, useState, useEffect, useRef } from "react";
import { onboardingReducer, initialState } from "./reducer";
import {
  OnboardingActions,
  OnboardingActionType,
  OnboardingData,
  OnboardingState,
  OnboardingStep,
} from "./types";
import { WellKnownLLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import { updateUserPersonalization } from "@/lib/userSettings";
import { useUser } from "@/providers/UserProvider";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { useLLMProviders } from "@/lib/hooks/useLLMProviders";

export function useOnboardingState(liveAssistant?: MinimalPersonaSnapshot): {
  state: OnboardingState;
  llmDescriptors: WellKnownLLMProviderDescriptor[];
  actions: OnboardingActions;
  isLoading: boolean;
} {
  const [state, dispatch] = useReducer(onboardingReducer, initialState);
  const { user, refreshUser } = useUser();
  // Use the SWR hook for LLM providers - no persona ID for the general providers list
  const {
    llmProviders,
    isLoading: isLoadingProviders,
    refetch: refreshLlmProviders,
  } = useLLMProviders();
  const { refetch: refreshPersonaProviders } = useLLMProviders(
    liveAssistant?.id
  );
  const hasLlmProviders = (llmProviders?.length ?? 0) > 0;
  const userName = user?.personalization?.name;
  const [llmDescriptors, setLlmDescriptors] = useState<
    WellKnownLLMProviderDescriptor[]
  >([]);
  const nameUpdateTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(
    null
  );

  useEffect(() => {
    refreshLlmProviders();
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

  // Navigate to the earliest incomplete step in the onboarding flow.
  // Step order: Welcome -> Name -> LlmSetup -> Complete
  // We check steps in order and stop at the first incomplete one.
  useEffect(() => {
    // Don't run logic until data has loaded
    if (isLoadingProviders) {
      return;
    }

    // Pre-populate state with existing data
    if (userName) {
      dispatch({
        type: OnboardingActionType.UPDATE_DATA,
        payload: { userName },
      });
    }
    if (hasLlmProviders) {
      dispatch({
        type: OnboardingActionType.UPDATE_DATA,
        payload: { llmProviders: (llmProviders ?? []).map((p) => p.provider) },
      });
    }

    // Determine the earliest incomplete step
    // Name step is incomplete if userName is not set
    if (!userName) {
      // Stay at Welcome/Name step (no dispatch needed, this is the initial state)
      return;
    }

    // LlmSetup step is incomplete if no LLM providers are configured
    if (!hasLlmProviders) {
      dispatch({
        type: OnboardingActionType.SET_BUTTON_ACTIVE,
        isButtonActive: false,
      });
      dispatch({
        type: OnboardingActionType.GO_TO_STEP,
        step: OnboardingStep.LlmSetup,
      });
      return;
    }

    // All steps complete - go to Complete step
    dispatch({
      type: OnboardingActionType.SET_BUTTON_ACTIVE,
      isButtonActive: true,
    });
    dispatch({
      type: OnboardingActionType.GO_TO_STEP,
      step: OnboardingStep.Complete,
    });
  }, [llmProviders, isLoadingProviders]);

  const nextStep = useCallback(() => {
    dispatch({
      type: OnboardingActionType.SET_BUTTON_ACTIVE,
      isButtonActive: false,
    });

    if (state.currentStep === OnboardingStep.Name) {
      const hasProviders = state.data.llmProviders?.length || 0 > 0;
      if (hasProviders) {
        dispatch({
          type: OnboardingActionType.SET_BUTTON_ACTIVE,
          isButtonActive: true,
        });
      } else {
        dispatch({
          type: OnboardingActionType.SET_BUTTON_ACTIVE,
          isButtonActive: false,
        });
      }
    }

    if (state.currentStep === OnboardingStep.LlmSetup) {
      refreshLlmProviders();
      if (liveAssistant) {
        refreshPersonaProviders();
      }
    }
    dispatch({ type: OnboardingActionType.NEXT_STEP });
  }, [state, refreshLlmProviders, llmProviders, refreshPersonaProviders]);

  const prevStep = useCallback(() => {
    dispatch({ type: OnboardingActionType.PREV_STEP });
  }, []);

  const goToStep = useCallback(
    (step: OnboardingStep) => {
      const hasProviders = state.data.llmProviders?.length || 0 > 0;
      if (step === OnboardingStep.LlmSetup && hasProviders) {
        dispatch({
          type: OnboardingActionType.SET_BUTTON_ACTIVE,
          isButtonActive: true,
        });
      } else if (step === OnboardingStep.LlmSetup) {
        dispatch({
          type: OnboardingActionType.SET_BUTTON_ACTIVE,
          isButtonActive: false,
        });
      }
      dispatch({ type: OnboardingActionType.GO_TO_STEP, step });
    },
    [llmProviders]
  );

  const updateName = useCallback(
    (name: string) => {
      dispatch({
        type: OnboardingActionType.UPDATE_DATA,
        payload: { userName: name },
      });

      if (nameUpdateTimeoutRef.current) {
        clearTimeout(nameUpdateTimeoutRef.current);
      }

      if (name === "") {
        dispatch({
          type: OnboardingActionType.SET_BUTTON_ACTIVE,
          isButtonActive: false,
        });
      } else {
        dispatch({
          type: OnboardingActionType.SET_BUTTON_ACTIVE,
          isButtonActive: true,
        });
      }

      nameUpdateTimeoutRef.current = setTimeout(async () => {
        try {
          await updateUserPersonalization({ name });
          await refreshUser();
        } catch (_e) {
          dispatch({
            type: OnboardingActionType.SET_BUTTON_ACTIVE,
            isButtonActive: false,
          });
          console.error("Error updating user name:", _e);
        } finally {
          nameUpdateTimeoutRef.current = null;
        }
      }, 500);
    },
    [refreshUser]
  );

  const updateData = useCallback((data: Partial<OnboardingData>) => {
    dispatch({ type: OnboardingActionType.UPDATE_DATA, payload: data });
  }, []);

  const setLoading = useCallback((isLoading: boolean) => {
    dispatch({ type: OnboardingActionType.SET_LOADING, isLoading });
  }, []);

  const setButtonActive = useCallback((active: boolean) => {
    dispatch({
      type: OnboardingActionType.SET_BUTTON_ACTIVE,
      isButtonActive: active,
    });
  }, []);

  const setError = useCallback((error: string | undefined) => {
    dispatch({ type: OnboardingActionType.SET_ERROR, error });
  }, []);

  const reset = useCallback(() => {
    dispatch({ type: OnboardingActionType.RESET });
  }, []);

  useEffect(() => {
    return () => {
      if (nameUpdateTimeoutRef.current) {
        clearTimeout(nameUpdateTimeoutRef.current);
      }
    };
  }, []);

  return {
    state,
    llmDescriptors,
    actions: {
      nextStep,
      prevStep,
      goToStep,
      setButtonActive,
      updateName,
      updateData,
      setLoading,
      setError,
      reset,
    },
    isLoading: isLoadingProviders || !!liveAssistant,
  };
}
