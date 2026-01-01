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
}

export function useShowOnboarding({
  liveAssistant,
  isLoadingProviders,
  hasAnyProvider,
  isLoadingChatSessions,
  chatSessionsCount,
}: UseShowOnboardingParams) {
  const [showOnboarding, setShowOnboarding] = useState(false);

  // Initialize onboarding state
  const {
    state: onboardingState,
    actions: onboardingActions,
    llmDescriptors,
    isLoading: isLoadingOnboarding,
  } = useOnboardingState(liveAssistant);

  // On first render, open onboarding if there are no configured LLM providers
  // OR if the user hasn't explicitly finished onboarding yet.
  // Wait until both providers AND chat sessions have loaded before making this decision.
  // Skip onboarding entirely if the user has any existing chat sessions.
  const hasCheckedOnboarding = useRef(false);
  useEffect(() => {
    // Only check once, and only after both providers and chat sessions have loaded
    if (
      hasCheckedOnboarding.current ||
      isLoadingProviders ||
      isLoadingChatSessions
    ) {
      return;
    }
    hasCheckedOnboarding.current = true;

    // Skip onboarding if user has any chat sessions
    if (chatSessionsCount > 0) {
      setShowOnboarding(false);
      return;
    }

    // Check if user has explicitly finished onboarding
    const hasFinishedOnboarding =
      localStorage.getItem(HAS_FINISHED_ONBOARDING_KEY) === "true";

    // Show onboarding if:
    // 1. No LLM providers configured, OR
    // 2. User hasn't explicitly finished onboarding (they navigated away before clicking "Finish Setup")
    setShowOnboarding(hasAnyProvider === false || !hasFinishedOnboarding);
  }, [
    isLoadingProviders,
    isLoadingChatSessions,
    hasAnyProvider,
    chatSessionsCount,
  ]);

  const hideOnboarding = () => {
    setShowOnboarding(false);
  };

  const finishOnboarding = () => {
    localStorage.setItem(HAS_FINISHED_ONBOARDING_KEY, "true");
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
