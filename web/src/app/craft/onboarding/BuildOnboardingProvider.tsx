"use client";

import { createContext, useContext } from "react";
import { useRouter } from "next/navigation";
import { useOnboardingModal } from "@/app/craft/onboarding/hooks/useOnboardingModal";
import BuildOnboardingModal from "@/app/craft/onboarding/components/BuildOnboardingModal";
import NoLlmProvidersModal from "@/app/craft/onboarding/components/NoLlmProvidersModal";
import { OnboardingModalController } from "@/app/craft/onboarding/types";
import { useUser } from "@/providers/UserProvider";

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
  const router = useRouter();
  const { user } = useUser();
  const controller = useOnboardingModal();

  // Show loading state while user data is loading
  if (!user) {
    return (
      <div className="flex items-center justify-center w-full h-full">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-text-01" />
      </div>
    );
  }

  // Non-admins can't configure providers, so block them when none of the
  // supported providers is accessible.
  const showNoProvidersModal =
    !controller.isLoading && !controller.isAdmin && !controller.hasAnyProvider;

  return (
    <OnboardingContext.Provider value={controller}>
      <NoLlmProvidersModal
        open={showNoProvidersModal}
        onClose={() => router.push("/app")}
      />

      {!showNoProvidersModal && (
        <BuildOnboardingModal
          mode={controller.mode}
          llmProviders={controller.llmProviders}
          isAdmin={controller.isAdmin}
          hasAnyProvider={controller.hasAnyProvider}
          onComplete={controller.completeOnboarding}
          onLlmComplete={controller.completeLlmSetup}
          onClose={controller.close}
        />
      )}

      {children}
    </OnboardingContext.Provider>
  );
}
