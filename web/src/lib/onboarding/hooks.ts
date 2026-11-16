"use client";

import { useReducer, useCallback, useEffect, useRef, useState } from "react";
import { onboardingReducer, initialState } from "@/lib/onboarding/reducer";
import { STEP_CONFIG, STEP_NAVIGATION } from "@/lib/onboarding/constants";
import {
  OnboardingActions,
  OnboardingActionType,
  OnboardingData,
  OnboardingState,
  OnboardingStep,
} from "@/lib/onboarding/types";
import { updateUserPersonalization } from "@/lib/users/svc";
import { useUser } from "@/providers/UserProvider";
import { MinimalAgent } from "@/lib/agents/types";
import { useLanguageModelsForAgent } from "@/lib/languageModels/hooks";
import { useProviderStatus } from "@/components/chat/ProviderContext";

function getOnboardingCompletedKey(userId: string): string {
  return `onyx:onboardingCompleted:${userId}`;
}

// Saved progress lets onboarding resume at the same step after the user
// leaves the page (e.g. for an admin page) and comes back. It lives until
// onboarding is finished or dismissed.
function getOnboardingProgressKey(userId: string): string {
  return `onyx:onboardingProgress:${userId}`;
}

function isOnboardingStep(value: string | null): value is OnboardingStep {
  return Object.values(OnboardingStep).some((step) => step === value);
}

function readOnboardingProgress(userId: string): OnboardingStep | null {
  try {
    const saved = localStorage.getItem(getOnboardingProgressKey(userId));
    return isOnboardingStep(saved) ? saved : null;
  } catch {
    // Storage can be unavailable (e.g. blocked); onboarding then starts fresh.
    return null;
  }
}

function writeOnboardingProgress(userId: string, step: OnboardingStep): void {
  try {
    localStorage.setItem(getOnboardingProgressKey(userId), step);
  } catch {
    // Storage can be unavailable; the step just is not resumed later.
  }
}

function clearOnboardingProgress(userId: string): void {
  try {
    localStorage.removeItem(getOnboardingProgressKey(userId));
  } catch {
    // Storage can be unavailable; nothing to clear then.
  }
}

function useOnboardingState(activeAgent?: MinimalAgent): {
  state: OnboardingState;
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
    refreshProviderInfo,
  } = useProviderStatus();

  // Only fetch persona-specific providers (different endpoint)
  const { refetch: refreshPersonaProviders } = useLanguageModelsForAgent(
    activeAgent?.id
  );

  const userName = user?.personalization?.name;

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
      // A failed provider request leaves no list; resuming then would treat
      // a connected provider as missing.
      llmProviders === undefined ||
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

    // Resume where the user left off, as long as every earlier step is still
    // done. Otherwise, fall through to the earliest incomplete step.
    const savedStep = readOnboardingProgress(user.id);
    const furthestReachable = !userName
      ? OnboardingStep.Name
      : !hasLlmProviders
        ? OnboardingStep.LlmSetup
        : OnboardingStep.PostStep;
    if (
      savedStep !== null &&
      STEP_CONFIG[savedStep].index <= STEP_CONFIG[furthestReachable].index
    ) {
      dispatch({
        type: OnboardingActionType.SET_BUTTON_ACTIVE,
        isButtonActive:
          savedStep === OnboardingStep.Name
            ? !!userName
            : savedStep === OnboardingStep.LlmSetup
              ? hasLlmProviders
              : true,
      });
      dispatch({ type: OnboardingActionType.GO_TO_STEP, step: savedStep });
      return;
    }

    // Determine the earliest incomplete step
    // Name step is incomplete if userName is not set
    if (!userName) {
      // Stay at the pre-step (no dispatch needed, this is the initial state)
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

    // The required steps are done - go to the optional setup step
    dispatch({
      type: OnboardingActionType.SET_BUTTON_ACTIVE,
      isButtonActive: true,
    });
    dispatch({
      type: OnboardingActionType.GO_TO_STEP,
      step: OnboardingStep.OptionalSetup,
    });
  }, [llmProviders, isLoadingProviders, userName, hasLlmProviders, user]);

  const nextStep = useCallback(() => {
    dispatch({
      type: OnboardingActionType.SET_BUTTON_ACTIVE,
      isButtonActive: false,
    });

    // A name already filled in (saved earlier or typed before) lets the
    // Name step continue without another keystroke.
    if (state.currentStep === OnboardingStep.PreStep) {
      dispatch({
        type: OnboardingActionType.SET_BUTTON_ACTIVE,
        isButtonActive: !!state.data.userName?.trim(),
      });
    }

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
      if (activeAgent) {
        refreshPersonaProviders();
      }
    }
    dispatch({ type: OnboardingActionType.NEXT_STEP });
  }, [state, refreshProviderInfo, refreshPersonaProviders, activeAgent]);

  const prevStep = useCallback(() => {
    // The step landed on decides whether Next can be pressed there.
    const target = STEP_NAVIGATION[state.currentStep].prev;
    if (target !== undefined) {
      const isActive =
        target === OnboardingStep.Name
          ? !!state.data.userName?.trim()
          : target === OnboardingStep.LlmSetup
            ? (state.data.llmProviders?.length ?? 0) > 0
            : true;
      dispatch({
        type: OnboardingActionType.SET_BUTTON_ACTIVE,
        isButtonActive: isActive,
      });
    }
    dispatch({ type: OnboardingActionType.PREV_STEP });
  }, [state]);

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
  activeAgent: MinimalAgent | undefined;
  isLoadingChatSessions: boolean;
  chatSessionsCount: number;
  userId: string | undefined;
}

export function useShowOnboarding({
  activeAgent,
  isLoadingChatSessions,
  chatSessionsCount,
  userId,
}: UseShowOnboardingParams) {
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [onboardingDismissed, setOnboardingDismissed] = useState(false);
  const { isAdmin } = useUser();

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
    isLoading: isLoadingOnboarding,
    hasProviders: hasAnyProvider,
  } = useOnboardingState(activeAgent);

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

    // Onboarding left mid-way comes back, even once a provider exists.
    const hasSavedProgress = readOnboardingProgress(userId) !== null;

    // Only check once per user — but allow self-correction from true→false
    // when provider data arrives (e.g. after a transient fetch error).
    if (hasCheckedOnboardingForUserId.current === userId) {
      if (
        showOnboarding &&
        hasAnyProvider &&
        onboardingState.stepIndex === 0 &&
        !hasSavedProgress
      ) {
        setShowOnboarding(false);
      }
      return;
    }
    hasCheckedOnboardingForUserId.current = userId;

    if (hasSavedProgress) {
      setShowOnboarding(true);
      return;
    }

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

  // Save the step while onboarding is showing, so a return resumes it. Users
  // who never see onboarding get nothing saved, and neither does the pre-step:
  // only a started onboarding has progress to resume. Only admins see the
  // full flow, so only their progress is saved.
  // On a user switch, the first run still holds the previous user's step, so
  // it saves nothing.
  const progressUserIdRef = useRef(userId);
  useEffect(() => {
    if (progressUserIdRef.current !== userId) {
      progressUserIdRef.current = userId;
      return;
    }
    if (
      !showOnboarding ||
      !isAdmin ||
      userId === undefined ||
      onboardingState.currentStep === OnboardingStep.PreStep
    ) {
      return;
    }
    writeOnboardingProgress(userId, onboardingState.currentStep);
  }, [showOnboarding, isAdmin, userId, onboardingState.currentStep]);

  const dismissOnboarding = useCallback(() => {
    if (userId === undefined) return;
    setShowOnboarding(false);
    setOnboardingDismissed(true);
    // Clear first: a failed write below must not leave progress that brings
    // onboarding back.
    clearOnboardingProgress(userId);
    try {
      localStorage.setItem(getOnboardingCompletedKey(userId), "true");
    } catch {
      // Storage can be unavailable; onboarding stays dismissed for this visit.
    }
  }, [userId]);

  const hideOnboarding = dismissOnboarding;
  const finishOnboarding = dismissOnboarding;

  return {
    showOnboarding,
    onboardingDismissed,
    onboardingState,
    onboardingActions,
    isLoadingOnboarding,
    hideOnboarding,
    finishOnboarding,
  };
}
