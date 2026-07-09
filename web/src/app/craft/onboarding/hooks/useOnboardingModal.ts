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
  const { llmProviders, isLoading: isLoadingLlm } = useLLMProviders();

  // Get ensurePreProvisionedSession from the session store
  const ensurePreProvisionedSession = useBuildSessionStore(
    (state) => state.ensurePreProvisionedSession
  );

  // Modal mode state
  const [mode, setMode] = useState<OnboardingModalMode>({ type: "closed" });
  const [hasInitialized, setHasInitialized] = useState(false);
  const [activeProviderKey, setActiveProviderKey] = useState<string | null>(
    null
  );

  const hasAnyProvider = useMemo(
    () => hasSupportedCraftProvider(llmProviders),
    [llmProviders]
  );

  // Auto-open the intro once (until dismissed). LLM setup lives inline on the
  // welcome page, so the intro is not conditioned on provider state.
  useEffect(() => {
    if (hasInitialized || !user) return;

    if (!getCraftOnboardingSeen()) {
      setMode({ type: "initial-onboarding" });
    }

    setHasInitialized(true);
  }, [hasInitialized, user]);

  // Complete onboarding callback — fired when the intro is done
  const completeOnboarding = useCallback(async () => {
    setCraftOnboardingSeen();

    // Trigger pre-provisioning now that onboarding is complete so the sandbox
    // starts provisioning immediately rather than waiting for the controller.
    // With no supported provider, session create would fail and the resulting
    // backoff would delay the sandbox after a provider is finally connected —
    // the connect success path kicks provisioning off instead.
    if (hasAnyProvider) {
      ensurePreProvisionedSession();
    }
  }, [ensurePreProvisionedSession, hasAnyProvider]);

  // Any well-known provider type — getProvider resolves the matching modal.
  const openProviderModal = useCallback((providerKey: string) => {
    setActiveProviderKey(providerKey);
  }, []);

  const closeProviderModal = useCallback(() => {
    setActiveProviderKey(null);
  }, []);

  const close = useCallback(() => {
    setMode({ type: "closed" });
  }, []);

  const isOpen = mode.type !== "closed";

  return {
    mode,
    isOpen,
    close,
    completeOnboarding,
    activeProviderKey,
    openProviderModal,
    closeProviderModal,
    llmProviders,
    isAdmin,
    hasAnyProvider,
    isLoading: isLoadingLlm,
  };
}
