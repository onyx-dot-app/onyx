"use client";

import { useCallback, useState } from "react";
import { useUser } from "@/components/user/UserProvider";
import { useLLMProviders } from "@/lib/hooks/useLLMProviders";
import {
  LLMProviderDescriptor,
  LLMProviderName,
} from "@/app/admin/configuration/llm/interfaces";
import { BuildOnboardingFlow, BuildUserInfo } from "../types";
import { getBuildUserPersona, setBuildUserPersona } from "../constants";
import { updateUserPersonalization } from "@/lib/userSettings";

function checkHasRecommendedLlms(
  llmProviders: LLMProviderDescriptor[] | undefined
): boolean {
  if (!llmProviders || llmProviders.length === 0) {
    return false;
  }
  // Check if Anthropic is configured as recommended LLM
  return llmProviders.some(
    (provider) => provider.provider === LLMProviderName.ANTHROPIC
  );
}

export function useBuildOnboarding() {
  const { user, isAdmin, isCurator, refreshUser } = useUser();
  const { llmProviders, isLoading: isLoadingLlm, refetch } = useLLMProviders();
  const [isSubmitting, setIsSubmitting] = useState(false);

  const existingPersona = getBuildUserPersona();
  const hasUserInfo = !!(
    user?.personalization?.name && existingPersona?.workArea
  );
  const hasRecommendedLlms = checkHasRecommendedLlms(llmProviders);

  const flow: BuildOnboardingFlow = {
    showNotAllowedModal: false,
    showUserInfoModal: !hasUserInfo,
    showLlmModal: isAdmin && !hasRecommendedLlms,
  };

  const completeUserInfo = useCallback(
    async (info: BuildUserInfo) => {
      setIsSubmitting(true);
      try {
        // Save name via API
        const fullName = `${info.firstName} ${info.lastName}`.trim();
        await updateUserPersonalization({
          name: fullName,
        });

        // Save persona to single consolidated cookie
        setBuildUserPersona({
          workArea: info.workArea,
          level: info.level,
        });

        // Refresh user to update the flow
        await refreshUser();
      } finally {
        setIsSubmitting(false);
      }
    },
    [refreshUser]
  );

  const completeLlmSetup = useCallback(async () => {
    // Refetch LLM providers to update the flow
    await refetch();
  }, [refetch]);

  const isLoading = isLoadingLlm || !user;

  // Get existing personalization data for pre-filling the form
  const existingName = user?.personalization?.name || "";

  // Split name on first space
  const spaceIndex = existingName.indexOf(" ");
  const initialFirstName =
    spaceIndex > 0 ? existingName.slice(0, spaceIndex) : existingName;
  const initialLastName =
    spaceIndex > 0 ? existingName.slice(spaceIndex + 1) : "";

  return {
    flow,
    actions: {
      completeUserInfo,
      completeLlmSetup,
    },
    isLoading,
    isSubmitting,
    llmProviders,
    initialValues: {
      firstName: initialFirstName,
      lastName: initialLastName,
      workArea: existingPersona?.workArea || "",
      level: existingPersona?.level || "",
    },
  };
}
