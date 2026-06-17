"use client";

import { useCallback, useState, useMemo, useEffect } from "react";
import { useUser } from "@/providers/UserProvider";
import { useLLMProviders } from "@/lib/languageModels/hooks";
import {
  OnboardingModalMode,
  OnboardingModalController,
} from "@/app/craft/onboarding/types";
import {
  getCraftOnboardingSeen,
  setCraftOnboardingSeen,
  hasSupportedCraftProvider,
} from "@/app/craft/onboarding/constants";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";

export function useOnboardingModal(): OnboardingModalController {
  const { user, isAdmin } = useUser();
  const {
    llmProviders,
    isLoading: isLoadingLlm,
    refetch: refetchLlmProviders,
  } = useLLMProviders();

  // Get ensurePreProvisionedSession from the session store
  const ensurePreProvisionedSession = useBuildSessionStore(
    (state) => state.ensurePreProvisionedSession
  );

  // Modal mode state
  const [mode, setMode] = useState<OnboardingModalMode>({ type: "closed" });
  const [hasInitialized, setHasInitialized] = useState(false);

  const hasAnyProvider = useMemo(
    () => hasSupportedCraftProvider(llmProviders),
    [llmProviders]
  );

  // Auto-open initial onboarding modal on first load.
  // Shows the intro once (until dismissed) and the LLM setup step when an
  // admin has no supported provider configured yet.
  useEffect(() => {
    if (hasInitialized || isLoadingLlm || !user) return;

    const needsOnboarding = !getCraftOnboardingSeen();
    const needsLlmSetup = isAdmin && !hasAnyProvider;

    if (needsOnboarding || needsLlmSetup) {
      setMode({ type: "initial-onboarding" });
    }

    setHasInitialized(true);
  }, [hasInitialized, isLoadingLlm, user, isAdmin, hasAnyProvider]);

  // Complete onboarding callback — fired when the intro / LLM setup flow is done
  const completeOnboarding = useCallback(async () => {
    setCraftOnboardingSeen();

    // Trigger pre-provisioning now that onboarding is complete so the sandbox
    // starts provisioning immediately rather than waiting for the controller.
    ensurePreProvisionedSession();
  }, [ensurePreProvisionedSession]);

  // Complete LLM setup callback
  const completeLlmSetup = useCallback(async () => {
    await refetchLlmProviders();
  }, [refetchLlmProviders]);

  // Actions
  const openLlmSetup = useCallback((provider?: string) => {
    setMode({ type: "add-llm", provider });
  }, []);

  const close = useCallback(() => {
    setMode({ type: "closed" });
  }, []);

  const isOpen = mode.type !== "closed";

  return {
    mode,
    isOpen,
    openLlmSetup,
    close,
    llmProviders,
    completeOnboarding,
    completeLlmSetup,
    refetchLlmProviders,
    isAdmin,
    hasAnyProvider,
    isLoading: isLoadingLlm,
  };
}
