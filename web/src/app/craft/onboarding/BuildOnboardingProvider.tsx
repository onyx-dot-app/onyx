"use client";

import { createContext, useContext } from "react";
import { useSWRConfig } from "swr";
import { useOnboardingModal } from "@/app/craft/onboarding/hooks/useOnboardingModal";
import BuildOnboardingModal from "@/app/craft/onboarding/components/BuildOnboardingModal";
import { OnboardingModalController } from "@/app/craft/onboarding/types";
import ProviderSetupModal from "@/sections/modals/languageModels/ProviderSetupModal";
import { refreshLlmProviderCaches } from "@/lib/languageModels/cache";
import { LLMProviderConfiguredSource } from "@/lib/analytics/utils";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import { useUser } from "@/providers/UserProvider";
import { toast } from "@/hooks/useToast";

// Context for accessing onboarding modal controls
const OnboardingContext = createContext<OnboardingModalController | null>(null);

export function useOnboarding(): OnboardingModalController {
  const ctx = useContext(OnboardingContext);
  if (!ctx) {
    throw new Error(
      "useOnboarding must be used within BuildOnboardingProvider"
    );
  }
  return ctx;
}

interface BuildOnboardingProviderProps {
  children: React.ReactNode;
}

export function BuildOnboardingProvider({
  children,
}: BuildOnboardingProviderProps) {
  const { user } = useUser();
  const controller = useOnboardingModal();
  const { mutate } = useSWRConfig();
  const ensurePreProvisionedSession = useBuildSessionStore(
    (state) => state.ensurePreProvisionedSession
  );

  // Show loading state while user data is loading
  if (!user) {
    return (
      <div className="flex items-center justify-center w-full h-full">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-text-01" />
      </div>
    );
  }

  return (
    <OnboardingContext.Provider value={controller}>
      <BuildOnboardingModal
        mode={controller.mode}
        onComplete={controller.completeOnboarding}
        onClose={controller.close}
      />

      <ProviderSetupModal
        providerKey={controller.activeProviderKey}
        shouldMarkAsDefault={(controller.llmProviders ?? []).length === 0}
        analyticsSource={LLMProviderConfiguredSource.CRAFT_ONBOARDING}
        onOpenChange={(open) => {
          if (!open) controller.closeProviderModal();
        }}
        onSuccess={async () => {
          await refreshLlmProviderCaches(mutate);
          toast.success("Provider connected!");
          ensurePreProvisionedSession();
        }}
      />

      {children}
    </OnboardingContext.Provider>
  );
}
