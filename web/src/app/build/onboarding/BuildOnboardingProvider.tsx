"use client";

import { createContext, useContext } from "react";
import { useRouter } from "next/navigation";
import { useOnboardingModal } from "@/app/build/onboarding/hooks/useOnboardingModal";
import BuildOnboardingModal from "@/app/build/onboarding/components/BuildOnboardingModal";
import NoLlmProvidersModal from "@/app/build/onboarding/components/NoLlmProvidersModal";
import { OnboardingModalController } from "@/app/build/onboarding/types";
import { useUser } from "@/components/user/UserProvider";

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

  // Non-admin users with no LLM providers cannot use Craft
  // Don't show modal while loading to prevent flash
  const showNoProvidersModal =
    !controller.isLoading && !controller.isAdmin && !controller.hasAnyProvider;

  return (
    <OnboardingContext.Provider value={controller}>
      {/* Block non-admin users when no LLM providers are configured */}
      <NoLlmProvidersModal
        open={showNoProvidersModal}
        onClose={() => router.push("/chat")}
      />

      {/* Unified onboarding modal - only show if not blocked by no providers */}
      {!showNoProvidersModal && (
        <BuildOnboardingModal
          mode={controller.mode}
          llmProviders={controller.llmProviders}
          initialValues={controller.initialValues}
          isAdmin={controller.isAdmin}
          hasUserInfo={controller.hasUserInfo}
          allProvidersConfigured={controller.allProvidersConfigured}
          hasAnyProvider={controller.hasAnyProvider}
          onComplete={controller.completeUserInfo}
          onLlmComplete={controller.completeLlmSetup}
          onClose={controller.close}
        />
      )}

      {/* Build content - always rendered, modals overlay it */}
      {children}
    </OnboardingContext.Provider>
  );
}
