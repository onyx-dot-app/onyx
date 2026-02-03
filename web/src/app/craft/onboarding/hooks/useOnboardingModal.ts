"use client";

import { useCallback, useState, useMemo, useEffect } from "react";
import { useUser } from "@/providers/UserProvider";
import { useLLMProviders } from "@/lib/hooks/useLLMProviders";
import { LLMProviderName } from "@/app/admin/configuration/llm/interfaces";
import {
  OnboardingModalMode,
  OnboardingModalController,
  BuildUserInfo,
} from "@/app/craft/onboarding/types";
import {
  getBuildUserPersona,
  setBuildUserPersona,
} from "@/app/craft/onboarding/constants";
import { updateUserPersonalization } from "@/lib/userSettings";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";

// Check if all 3 build mode providers are configured (anthropic, openai, openrouter)
function checkAllProvidersConfigured(
  llmProviders:
    | import("@/app/admin/configuration/llm/interfaces").LLMProviderDescriptor[]
    | undefined
): boolean {
  if (!llmProviders || llmProviders.length === 0) {
    return false;
  }
  const configuredProviders = new Set(llmProviders.map((p) => p.provider));
  return (
    configuredProviders.has(LLMProviderName.ANTHROPIC) &&
    configuredProviders.has(LLMProviderName.OPENAI) &&
    configuredProviders.has(LLMProviderName.OPENROUTER)
  );
}

// Check if at least one provider is configured
function checkHasAnyProvider(
  llmProviders:
    | import("@/app/admin/configuration/llm/interfaces").LLMProviderDescriptor[]
    | undefined
): boolean {
  return !!(llmProviders && llmProviders.length > 0);
}

export function useOnboardingModal(): OnboardingModalController {
  const { user, isAdmin, refreshUser } = useUser();
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

  // Compute initial values for the form (read fresh on every render)
  const existingPersona = getBuildUserPersona();
  const existingName = user?.personalization?.name || "";
  const spaceIndex = existingName.indexOf(" ");
  const initialFirstName =
    spaceIndex > 0 ? existingName.slice(0, spaceIndex) : existingName;
  const initialLastName =
    spaceIndex > 0 ? existingName.slice(spaceIndex + 1) : "";

  const initialValues = {
    firstName: initialFirstName,
    lastName: initialLastName,
    workArea: existingPersona?.workArea,
    level: existingPersona?.level,
  };

  // Check if user has completed initial onboarding
  const hasUserInfo = useMemo(() => {
    const existingPersona = getBuildUserPersona();
    return !!(user?.personalization?.name && existingPersona?.workArea);
  }, [user?.personalization?.name]);

  // Check if all providers are configured (skip LLM step entirely if so)
  const allProvidersConfigured = useMemo(
    () => checkAllProvidersConfigured(llmProviders),
    [llmProviders]
  );

  // Check if at least one provider is configured (allow skipping LLM step)
  const hasAnyProvider = useMemo(
    () => checkHasAnyProvider(llmProviders),
    [llmProviders]
  );

  // Auto-open initial onboarding modal on first load
  // Shows if: user info is missing OR (admin AND no providers configured)
  useEffect(() => {
    if (hasInitialized || isLoadingLlm || !user) return;

    const needsUserInfo = !hasUserInfo;
    const needsLlmSetup = isAdmin && !hasAnyProvider;

    if (needsUserInfo || needsLlmSetup) {
      setMode({ type: "initial-onboarding" });
    }

    setHasInitialized(true);
  }, [
    hasInitialized,
    isLoadingLlm,
    user,
    hasUserInfo,
    isAdmin,
    hasAnyProvider,
  ]);

  // Complete user info callback
  const completeUserInfo = useCallback(
    async (info: BuildUserInfo) => {
      // Save name via API (handle optional lastName)
      const fullName = info.lastName
        ? `${info.firstName} ${info.lastName}`.trim()
        : info.firstName.trim();
      await updateUserPersonalization({ name: fullName });

      // Save persona to cookie
      setBuildUserPersona({
        workArea: info.workArea,
        level: info.level,
      });

      // Refresh user to update state
      await refreshUser();

      // Trigger pre-provisioning now that onboarding is complete
      // This ensures the sandbox starts provisioning immediately rather than
      // waiting for the controller effect to detect the cookie change
      ensurePreProvisionedSession();
    },
    [refreshUser, ensurePreProvisionedSession]
  );

  // Complete LLM setup callback
  const completeLlmSetup = useCallback(async () => {
    await refetchLlmProviders();
  }, [refetchLlmProviders]);

  // Actions
  const openPersonaEditor = useCallback(() => {
    setMode({ type: "edit-persona" });
  }, []);

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
    openPersonaEditor,
    openLlmSetup,
    close,
    llmProviders,
    initialValues,
    completeUserInfo,
    completeLlmSetup,
    refetchLlmProviders,
    isAdmin,
    hasUserInfo,
    allProvidersConfigured,
    hasAnyProvider,
    isLoading: isLoadingLlm,
  };
}
