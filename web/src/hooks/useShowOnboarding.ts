"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { useOnboardingState } from "@/refresh-components/onboarding/useOnboardingState";

const ONBOARDING_COMPLETED_KEY = "onyx:onboardingCompleted";
interface UseShowOnboardingParams {
  liveAssistant: MinimalPersonaSnapshot | undefined;
  isLoadingProviders: boolean;
  hasAnyProvider: boolean | undefined;
  isLoadingChatSessions: boolean;
  chatSessionsCount: number;
  userId: string | undefined;
}

export function useShowOnboarding({
  liveAssistant,
  isLoadingProviders,
  hasAnyProvider,
  isLoadingChatSessions,
  chatSessionsCount,
  userId,
}: UseShowOnboardingParams) {
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [onboardingDismissed, setOnboardingDismissed] = useState(() => {
    if (typeof window === "undefined") return false;
    return localStorage.getItem(ONBOARDING_COMPLETED_KEY) === "true";
  });

  // Initialize onboarding state
  const {
    state: onboardingState,
    actions: onboardingActions,
    llmDescriptors,
    isLoading: isLoadingOnboarding,
  } = useOnboardingState(liveAssistant);

  // Track which user we've already evaluated onboarding for.
  // Re-check when userId changes (logout/login, account switching without full reload).
  const hasCheckedOnboardingForUserId = useRef<string | undefined>(undefined);

  // Evaluate onboarding once per user after data loads.
  // Show onboarding only if no LLM providers are configured.
  // Skip entirely if user has existing chat sessions.
  useEffect(() => {
    // If onboarding was previously dismissed, never show it again
    if (onboardingDismissed) {
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
    setShowOnboarding(false);
    setOnboardingDismissed(true);
    localStorage.setItem(ONBOARDING_COMPLETED_KEY, "true");
  }, []);

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
