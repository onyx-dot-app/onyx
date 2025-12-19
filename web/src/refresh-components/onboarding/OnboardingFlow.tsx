import { memo } from "react";
import OnboardingHeader from "./components/OnboardingHeader";
import NameStep from "./steps/NameStep";
import LLMStep from "./steps/LLMStep";
import FinalStep from "./steps/FinalStep";
import { OnboardingActions, OnboardingState, OnboardingStep } from "./types";
import { WellKnownLLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import { useUser } from "@/components/user/UserProvider";
import { UserRole } from "@/lib/types";
import NonAdminStep from "./components/NonAdminStep";

type OnboardingFlowProps = {
  handleHideOnboarding: () => void;
  state: OnboardingState;
  actions: OnboardingActions;
  llmDescriptors: WellKnownLLMProviderDescriptor[];
};

const OnboardingFlowInner = ({
  handleHideOnboarding,
  state: onboardingState,
  actions: onboardingActions,
  llmDescriptors,
}: OnboardingFlowProps) => {
  const { user } = useUser();
  const hasStarted = onboardingState.currentStep !== OnboardingStep.Welcome;

  return user?.role === UserRole.ADMIN ? (
    <div className="flex flex-col items-center justify-center w-full max-w-[800px] gap-2 mb-4">
      <OnboardingHeader
        state={onboardingState}
        actions={onboardingActions}
        handleHideOnboarding={handleHideOnboarding}
      />
      {hasStarted && (
        <div className="relative w-full overflow-hidden">
          <div className="flex flex-col gap-2 animate-in slide-in-from-right duration-500 ease-out">
            <NameStep state={onboardingState} actions={onboardingActions} />
            <LLMStep
              state={onboardingState}
              actions={onboardingActions}
              llmDescriptors={llmDescriptors}
              disabled={onboardingState.currentStep !== OnboardingStep.LlmSetup}
            />
            <div
              className={
                "transition-all duration-500 ease-out " +
                (onboardingState.currentStep === OnboardingStep.Complete
                  ? "opacity-100 translate-x-0"
                  : "opacity-0 translate-x-full")
              }
            >
              {onboardingState.currentStep === OnboardingStep.Complete && (
                <FinalStep />
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  ) : !user?.personalization?.name ? (
    <NonAdminStep />
  ) : null;
};

const OnboardingFlow = memo(OnboardingFlowInner);
export default OnboardingFlow;
