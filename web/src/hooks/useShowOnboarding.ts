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
import { useLLMProviders } from "@/hooks/useLLMProviders";
import { useProviderStatus } from "@/components/chat/ProviderContext";

const ONBOARDING_COMPLETED_KEY_PREFIX = "activa:onboardingCompleted:";
const LEGACY_ONBOARDING_COMPLETED_KEY_PREFIX = "onyx:onboardingCompleted:";

function getOnboardingCompletedKey(userId: string): string {
  return `${ONBOARDING_COMPLETED_KEY_PREFIX}${userId}`;
}

function getLegacyOnboardingCompletedKey(userId: string): string {
  return `${LEGACY_ONBOARDING_COMPLETED_KEY_PREFIX}${userId}`;
}

function getOnboardingDismissed(userId: string): boolean {
  const onboardingCompletedKey = getOnboardingCompletedKey(userId);
  const dismissed = localStorage.getItem(onboardingCompletedKey);

  if (dismissed !== null) {
    return dismissed === "true";
  }

  const legacyKey = getLegacyOnboardingCompletedKey(userId);
  const legacyDismissed = localStorage.getItem(legacyKey);

  if (legacyDismissed !== null) {
    localStorage.setItem(onboardingCompletedKey, legacyDismissed);
    localStorage.removeItem(legacyKey);
    return legacyDismissed === "true";
  }

  return false;
}

function markOnboardingDismissed(userId: string): void {
  localStorage.setItem(getOnboardingCompletedKey(userId), "true");
  localStorage.removeItem(getLegacyOnboardingCompletedKey(userId));
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

  // Get provider data from ProviderContext instead of duplicating the call
  const {
    llmProviders,
    isLoadingProviders,
    hasProviders: hasLlmProviders,
    providerOptions,
    refreshProviderInfo,
  } = useProviderStatus();

  // Only fetch persona-specific providers (different endpoint)
  const { refetch: refreshPersonaProviders } = useLLMProviders(liveAgent?.id);

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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [llmProviders, isLoadingProviders, userName, hasLlmProviders, user]);

  const nextStep = useCallback(() => {
    dispatch({
      type: OnboardingActionType.SET_BUTTON_ACTIVE,
      isButtonActive: false,
    });

    if (state.currentStep === OnboardingStep.Name) {
      const hasProviders = (state.data.llmProviders?.length ?? 0) > 0;
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
      refreshProviderInfo();
      if (liveAgent) {
        refreshPersonaProviders();
      }
    }
    dispatch({ type: OnboardingActionType.NEXT_STEP });
  }, [state, refreshProviderInfo, refreshPersonaProviders, liveAgent]);

  const prevStep = useCallback(() => {
    dispatch({ type: OnboardingActionType.PREV_STEP });
  }, []);

  const goToStep = useCallback(
    (step: OnboardingStep) => {
      const hasProviders = (state.data.llmProviders?.length ?? 0) > 0;
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
    [state]
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
    setOnboardingDismissed(getOnboardingDismissed(userId));
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

    // Only check once per user — but allow self-correction from true→false
    // when provider data arrives (e.g. after a transient fetch error).
    if (hasCheckedOnboardingForUserId.current === userId) {
      if (showOnboarding && hasAnyProvider && onboardingState.stepIndex === 0) {
        setShowOnboarding(false);
      }
      return;
    }
    hasCheckedOnboardingForUserId.current = userId;

    // Skip onboarding if user has any chat sessions
    if (chatSessionsCount > 0) {
      setShowOnboarding(false);
      return;
    }

    // Show onboarding if no LLM providers are configured.
    setShowOnboarding(hasAnyProvider === false);
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
    markOnboardingDismissed(userId);
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
