"use client";

import { memo, useState } from "react";
import { Presence, type PresenceSwapDirection } from "@opal/components";
import OnboardingHeader from "@/lib/onboarding/components/OnboardingHeader";
import NameStep from "@/lib/onboarding/components/NameStep";
import LLMStep from "@/lib/onboarding/components/LLMStep";
import FinalStep from "@/lib/onboarding/components/FinalStep";
import { STEP_CONFIG } from "@/lib/onboarding/constants";
import {
  OnboardingActions,
  OnboardingState,
  OnboardingStep,
} from "@/lib/onboarding/types";
import { useUser } from "@/providers/UserProvider";
import NonAdminStep from "@/lib/onboarding/components/NonAdminStep";

type OnboardingFlowProps = {
  showOnboarding: boolean;
  handleHideOnboarding: () => void;
  handleFinishOnboarding: () => void;
  state: OnboardingState;
  actions: OnboardingActions;
};

interface StepContentProps {
  step: OnboardingStep;
  state: OnboardingState;
  actions: OnboardingActions;
}

/** The card for one step. Welcome has no card of its own. */
function StepContent({ step, state, actions }: StepContentProps) {
  switch (step) {
    case OnboardingStep.Name:
      return <NameStep state={state} actions={actions} />;
    case OnboardingStep.LlmSetup:
      return <LLMStep state={state} actions={actions} />;
    case OnboardingStep.Complete:
      return <FinalStep />;
    default:
      return null;
  }
}

const OnboardingFlowInner = ({
  showOnboarding,
  handleHideOnboarding,
  handleFinishOnboarding,
  state: onboardingState,
  actions: onboardingActions,
}: OnboardingFlowProps) => {
  const { user, isAdmin } = useUser();

  // One step shows at a time. The swap direction follows the step order.
  const [lastStep, setLastStep] = useState(onboardingState.currentStep);
  const [direction, setDirection] = useState<PresenceSwapDirection>("forward");
  if (onboardingState.currentStep !== lastStep) {
    setDirection(
      STEP_CONFIG[onboardingState.currentStep].index >
        STEP_CONFIG[lastStep].index
        ? "forward"
        : "back"
    );
    setLastStep(onboardingState.currentStep);
  }

  if (!user) return null;

  return isAdmin ? (
    showOnboarding ? (
      <div
        className="flex flex-col items-center justify-center w-full gap-2"
        aria-label="onboarding-flow"
      >
        <OnboardingHeader
          state={onboardingState}
          actions={onboardingActions}
          handleHideOnboarding={handleHideOnboarding}
          handleFinishOnboarding={handleFinishOnboarding}
        />
        {/* Mounted from Welcome on (with no content), so the first step
            also opens its height and fades in. */}
        <Presence.Swap
          swapKey={onboardingState.currentStep}
          direction={direction}
        >
          <StepContent
            step={onboardingState.currentStep}
            state={onboardingState}
            actions={onboardingActions}
          />
        </Presence.Swap>
      </div>
    ) : (
      // When showOnboarding is false, the parent only renders this component
      // if the admin hasn't set their name.
      <NonAdminStep />
    )
  ) : !user.personalization?.name ? (
    <NonAdminStep />
  ) : null;
};

const OnboardingFlow = memo(OnboardingFlowInner);
export default OnboardingFlow;
