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
import { updateUserPersonalization } from "@/lib/users/UserSettings";
import { useUser } from "@/components/user/UserProvider";
import { useChatContext } from "../contexts/ChatContext";

export function useOnboardingState(): {
  state: OnboardingState;
  llmDescriptors: WellKnownLLMProviderDescriptor[];
  actions: OnboardingActions;
} {
  const [state, dispatch] = useReducer(onboardingReducer, initialState);
  const { user, refreshUser } = useUser();
  const { llmProviders, refreshLlmProviders } = useChatContext();
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

  // If there are any configured LLM providers already present, skip to the final step
  useEffect(() => {
    if (Array.isArray(llmProviders) && llmProviders.length > 0) {
      dispatch({
        type: OnboardingActionType.UPDATE_DATA,
        payload: { llmProviders: llmProviders.map((p) => p.provider) },
      });
      dispatch({
        type: OnboardingActionType.GO_TO_STEP,
        step: OnboardingStep.Complete,
      });
      return;
    }
    if (userName && state.currentStep === OnboardingStep.Welcome) {
      dispatch({
        type: OnboardingActionType.UPDATE_DATA,
        payload: { userName },
      });
      if (llmProviders.length > 0) {
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
      dispatch({
        type: OnboardingActionType.GO_TO_STEP,
        step: OnboardingStep.LlmSetup,
      });
    }
  }, [llmProviders]);

  const nextStep = useCallback(() => {
    dispatch({
      type: OnboardingActionType.SET_BUTTON_ACTIVE,
      isButtonActive: false,
    });

    if (state.currentStep === OnboardingStep.Name) {
      if (llmProviders.length > 0) {
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
    }
    dispatch({ type: OnboardingActionType.NEXT_STEP });
  }, [state, refreshLlmProviders]);

  const prevStep = useCallback(() => {
    dispatch({ type: OnboardingActionType.PREV_STEP });
  }, []);

  const goToStep = useCallback(
    (step: OnboardingStep) => {
      if (step === OnboardingStep.LlmSetup && llmProviders.length > 0) {
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
  };
}
