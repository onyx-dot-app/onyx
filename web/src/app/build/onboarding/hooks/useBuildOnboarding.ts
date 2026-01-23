"use client";

import { useCallback, useState } from "react";
import { useUser } from "@/components/user/UserProvider";
import { useLLMProviders } from "@/lib/hooks/useLLMProviders";
import {
  LLMProviderDescriptor,
  LLMProviderName,
} from "@/app/admin/configuration/llm/interfaces";
import { BuildOnboardingFlow, BuildUserInfo } from "../types";
import {
  BUILD_USER_LEVEL_COOKIE_NAME,
  BUILD_USER_WORK_AREA_COOKIE_NAME,
} from "../constants";
import { updateUserPersonalization } from "@/lib/userSettings";
import Cookies from "js-cookie";

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

  const existingWorkArea = Cookies.get(BUILD_USER_WORK_AREA_COOKIE_NAME) || "";
  const hasUserInfo = !!(user?.personalization?.name && existingWorkArea);
  const hasRecommendedLlms = checkHasRecommendedLlms(llmProviders);
  const isBasicUser = !isAdmin && !isCurator;

  const showNotAllowedModal = isBasicUser;

  const flow: BuildOnboardingFlow = {
    showNotAllowedModal,
    showUserInfoModal:
      !showNotAllowedModal && !hasUserInfo && (isAdmin || isCurator),
    showLlmModal: !showNotAllowedModal && isAdmin && !hasRecommendedLlms,
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

        // Save work area to cookie
        Cookies.set(BUILD_USER_WORK_AREA_COOKIE_NAME, info.workArea, {
          path: "/",
          expires: 365,
        });

        // Save level to cookie if provided
        if (info.level) {
          Cookies.set(BUILD_USER_LEVEL_COOKIE_NAME, info.level, {
            path: "/",
            expires: 365,
          });
        }

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
  const existingLevel = Cookies.get(BUILD_USER_LEVEL_COOKIE_NAME) || "";

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
      workArea: existingWorkArea,
      level: existingLevel,
    },
  };
}
