"use client";

import { useCallback, useState, useMemo, useEffect } from "react";
import { useUser } from "@/providers/UserProvider";
import { useLLMProviders } from "@/lib/languageModels/hooks";
import { track, AnalyticsEvent } from "@/lib/analytics/utils";
import { OnboardingModalController } from "@/app/craft/onboarding/types";
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

  const [introOpen, setIntroOpen] = useState(false);
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
    setIntroOpen(!getCraftOnboardingSeen(user.id));
    setHasInitialized(true);
  }, [hasInitialized, user]);

  // Bail-out (Escape / X): remember the intro was seen, but don't count it as
  // a completion.
  const dismissOnboarding = useCallback(() => {
    if (user) setCraftOnboardingSeen(user.id);
    setIntroOpen(false);
  }, [user]);

  // Explicit finish (final CTA). Kicks off pre-provisioning early — unless no
  // provider exists yet, where session create would just fail (the connect
  // success path triggers it instead).
  const completeOnboarding = useCallback(() => {
    if (user) setCraftOnboardingSeen(user.id);
    track(AnalyticsEvent.COMPLETED_CRAFT_ONBOARDING);
    if (hasAnyProvider) {
      ensurePreProvisionedSession();
    }
    setIntroOpen(false);
  }, [user, ensurePreProvisionedSession, hasAnyProvider]);

  // Any well-known provider type — getProvider resolves the matching modal.
  const openProviderModal = useCallback((providerKey: string) => {
    setActiveProviderKey(providerKey);
  }, []);

  const closeProviderModal = useCallback(() => {
    setActiveProviderKey(null);
  }, []);

  return {
    introOpen,
    completeOnboarding,
    dismissOnboarding,
    activeProviderKey,
    openProviderModal,
    closeProviderModal,
    llmProviders,
    isAdmin,
    hasAnyProvider,
    isLoading: isLoadingLlm,
  };
}
