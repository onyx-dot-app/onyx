"use client";

import { useReducer, useCallback, useEffect, useRef, useState } from "react";
import { onboardingReducer, initialState } from "@/sections/onboarding/reducer";
import {
  OnboardingActions,
  OnboardingActionType,
  OnboardingData,
  OnboardingState,
  OnboardingStep,
} from "@/interfaces/onboarding";
import { WellKnownLLMProviderDescriptor } from "@/interfaces/llm";
import { updateUserPersonalization } from "@/lib/userSettings";
import { useUser } from "@/providers/UserProvider";
import { MinimalPersonaSnapshot } from "@/app/admin/agents/interfaces";
import { useProviderStatus } from "@/components/chat/ProviderContext";

function getOnboardingCompletedKey(userId: string): string {
  return `onyx:onboardingCompleted:${userId}`;
}

function useOnboardingState(liveAgent?: MinimalPersonaSnapshot): {
  state: OnboardingState;
  llmDescriptors: WellKnownLLMProviderDescriptor[];
  actions: OnboardingActions;
  isLoading: boolean;
  hasProviders: boolean;
} {
  const [state, dispatch] = useReducer(onboardingReducer, initialState);
  const { user, refreshUser } = useUser();

  // Get provider data from ProviderContext
  const {
    llmProviders,
    isLoadingProviders,
    hasProviders: hasLlmProviders,
    providerOptions,
  } = useProviderStatus();

  const userName = user?.personalization?.name;
  const llmDescriptors = providerOptions;

  const nameUpdateTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(
    null
  );
  const hasInitializedForUserRef = useRef<string | undefined>(undefined);

  // Initialize onboarding to the earliest incomplete step — runs once per user
  // after both user data and provider data have loaded.  After initialization,
  // user actions (Next / Prev / goToStep) drive navigation; the effect never
  // re-runs so it cannot override user-driven state (e.g. button active).
  useEffect(() => {
    if (
      isLoadingProviders ||
      !user ||
      hasInitializedForUserRef.current === user.id
    ) {
      return;
    }
    hasInitializedForUserRef.current = user.id;

    // Pre-populate state with existing data
    if (userName) {
      dispatch({
        type: OnboardingActionType.UPDATE_DATA,
        payload: { userName },
      });
    }
    dispatch({
      type: OnboardingActionType.UPDATE_DATA,
      payload: { llmProviders: (llmProviders ?? []).map((p) => p.provider) },
    });

    // Determine the earliest incomplete step
    // Name step is incomplete if userName is not set
    if (!userName) {
      // Stay at Welcome/Name step (no dispatch needed, this is the initial state)
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [llmProviders, isLoadingProviders, userName, hasLlmProviders, user]);

  const nextStep = useCallback(() => {
    dispatch({
      type: OnboardingActionType.SET_BUTTON_ACTIVE,
      isButtonActive: true,
    });

    dispatch({ type: OnboardingActionType.NEXT_STEP });
  }, []);

  const prevStep = useCallback(() => {
    dispatch({ type: OnboardingActionType.PREV_STEP });
  }, []);

  const goToStep = useCallback((step: OnboardingStep) => {
    dispatch({ type: OnboardingActionType.GO_TO_STEP, step });
  }, []);

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
    isLoading: isLoadingProviders,
    hasProviders: hasLlmProviders,
  };
}

interface UseShowOnboardingParams {
  liveAgent: MinimalPersonaSnapshot | undefined;
  isLoadingChatSessions: boolean;
  chatSessionsCount: number;
  userId: string | undefined;
}

export function useShowOnboarding({
  liveAgent,
  isLoadingChatSessions,
  chatSessionsCount,
  userId,
}: UseShowOnboardingParams) {
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [onboardingDismissed, setOnboardingDismissed] = useState(false);

  // Read localStorage once userId is available to check if onboarding was dismissed
  useEffect(() => {
    if (userId === undefined) return;
    const dismissed =
      localStorage.getItem(getOnboardingCompletedKey(userId)) === "true";
    setOnboardingDismissed(dismissed);
  }, [userId]);

  // Initialize onboarding state — single source of truth for provider data
  const {
    state: onboardingState,
    actions: onboardingActions,
    llmDescriptors,
    isLoading: isLoadingOnboarding,
    hasProviders: hasAnyProvider,
  } = useOnboardingState(liveAgent);

  const isLoadingProviders = isLoadingOnboarding;

  // Track which user we've already evaluated onboarding for.
  // Re-check when userId changes (logout/login, account switching without full reload).
  const hasCheckedOnboardingForUserId = useRef<string | undefined>(undefined);

  // Evaluate onboarding once per user after data loads.
  // Show onboarding only if no LLM providers are configured.
  // Skip entirely if user has existing chat sessions.
  useEffect(() => {
    // If onboarding was previously dismissed, never show it again
    if (onboardingDismissed) {
      setShowOnboarding(false);
      return;
    }

    // Wait for data to load
    if (isLoadingProviders || isLoadingChatSessions || userId === undefined) {
      return;
    }

    // Only check once per user
    if (hasCheckedOnboardingForUserId.current === userId) {
      return;
    }
    hasCheckedOnboardingForUserId.current = userId;

    // Skip onboarding if user has any chat sessions
    if (chatSessionsCount > 0) {
      setShowOnboarding(false);
      return;
    }

    // Show onboarding only for name setup (LLM is auto-configured).
    setShowOnboarding(true);
  }, [
    isLoadingProviders,
    isLoadingChatSessions,
    hasAnyProvider,
    chatSessionsCount,
    userId,
    showOnboarding,
    onboardingDismissed,
    onboardingState.stepIndex,
  ]);

  const dismissOnboarding = useCallback(() => {
    if (userId === undefined) return;
    setShowOnboarding(false);
    setOnboardingDismissed(true);
    localStorage.setItem(getOnboardingCompletedKey(userId), "true");
  }, [userId]);

  const hideOnboarding = dismissOnboarding;
  const finishOnboarding = dismissOnboarding;

  return {
    showOnboarding,
    onboardingDismissed,
    onboardingState,
    onboardingActions,
    llmDescriptors,
    isLoadingOnboarding,
    hideOnboarding,
    finishOnboarding,
  };
}
