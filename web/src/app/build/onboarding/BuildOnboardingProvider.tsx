"use client";

import { useBuildOnboarding } from "./hooks/useBuildOnboarding";
import NotAllowedModal from "./components/NotAllowedModal";
import BuildOnboardingModal from "./components/BuildOnboardingModal";

interface BuildOnboardingProviderProps {
  children: React.ReactNode;
}

export function BuildOnboardingProvider({
  children,
}: BuildOnboardingProviderProps) {
  const { flow, actions, isLoading, llmProviders, initialValues } =
    useBuildOnboarding();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center w-full h-full">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-text-01" />
      </div>
    );
  }

  // Show combined onboarding modal if user info or LLM setup is needed
  const showOnboardingModal = flow.showUserInfoModal || flow.showLlmModal;

  return (
    <>
      {/* Blocking modal - takes precedence */}
      <NotAllowedModal
        open={flow.showNotAllowedModal}
        onClose={actions.closeNotAllowedModal}
      />

      {/* Combined onboarding modal */}
      <BuildOnboardingModal
        open={showOnboardingModal && !flow.showNotAllowedModal}
        showLlmSetup={flow.showLlmModal}
        llmProviders={llmProviders}
        onComplete={actions.completeUserInfo}
        onLlmComplete={actions.completeLlmSetup}
        initialValues={initialValues}
      />

      {/* Build content - always rendered, modals overlay it */}
      {children}
    </>
  );
}
