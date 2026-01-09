"use client";

import { useEffect, useRef, useState } from "react";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { useOnboardingState } from "@/refresh-components/onboarding/useOnboardingState";
import { HAS_FINISHED_ONBOARDING_KEY } from "@/refresh-components/onboarding/constants";

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

  // Initialize onboarding state
  const {
    state: onboardingState,
    actions: onboardingActions,
    llmDescriptors,
    isLoading: isLoadingOnboarding,
  } = useOnboardingState(liveAssistant);

  // Create a per-user localStorage key to avoid cross-user pollution
  const onboardingKey = userId
    ? `${HAS_FINISHED_ONBOARDING_KEY}_${userId}`
    : HAS_FINISHED_ONBOARDING_KEY;

  // Track which user we've already evaluated onboarding for.
  // Re-check when userId changes (logout/login, account switching without full reload).
  const hasCheckedOnboardingForUserId = useRef<string | undefined>(undefined);

  // Evaluate onboarding once per user after data loads.
  // Show onboarding if no LLM providers OR user hasn't finished onboarding.
  // Skip entirely if user has existing chat sessions.
  useEffect(() => {
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

    // Check if user has explicitly finished onboarding (per-user key)
    const hasFinishedOnboarding =
      localStorage.getItem(onboardingKey) === "true";

    // Show onboarding if:
    // 1. No LLM providers configured, OR
    // 2. User hasn't explicitly finished onboarding (they navigated away before clicking "Finish Setup")
    setShowOnboarding(hasAnyProvider === false || !hasFinishedOnboarding);
  }, [
    isLoadingProviders,
    isLoadingChatSessions,
    hasAnyProvider,
    chatSessionsCount,
    userId,
    onboardingKey,
  ]);

  const hideOnboarding = () => {
    setShowOnboarding(false);
  };

  const finishOnboarding = () => {
    localStorage.setItem(onboardingKey, "true");
    setShowOnboarding(false);
  };

  return {
    showOnboarding,
    onboardingState,
    onboardingActions,
    llmDescriptors,
    isLoadingOnboarding,
    hideOnboarding,
    finishOnboarding,
  };
}
