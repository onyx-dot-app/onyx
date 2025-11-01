import React, { memo, useEffect, useState } from "react";
import OnboardingHeader from "./components/OnboardingHeader";
import NameStep from "./steps/NameStep";
import LLMStep from "./steps/LLMStep";
import FinalStep from "./steps/FinalStep";
import { useOnboardingState } from "./useOnboardingState";
import { OnboardingStep } from "./types";

type OnboardingFlowProps = {
  isCollapsed: boolean;
  onCollapsedChange: (collapsed: boolean) => void;
  handleHideOnboarding: () => void;
};

const OnboardingFlowInner = ({
  isCollapsed,
  onCollapsedChange,
  handleHideOnboarding,
}: OnboardingFlowProps) => {
  const {
    state: onboardingState,
    actions: onboardingActions,
    llmDescriptors,
  } = useOnboardingState();

  return (
    <div className="flex flex-col items-center justify-center w-full max-w-[800px] gap-2 mb-4">
      <OnboardingHeader
        state={onboardingState}
        actions={onboardingActions}
        onToggleCollapse={() => onCollapsedChange(!isCollapsed)}
        handleHideOnboarding={handleHideOnboarding}
      />
      <div
        className={
          "relative w-full overflow-hidden transition-all duration-300 ease-in-out " +
          (isCollapsed ? "max-h-0 opacity-0" : "max-h-[1000px] opacity-100")
        }
      >
        <div
          className={
            `flex w-[200%] transition-transform duration-300 ease-out ` +
            (onboardingState.currentStep === OnboardingStep.Complete
              ? "-translate-x-1/2"
              : "translate-x-0")
          }
        >
          <div className="w-1/2 shrink-0">
            <div className="flex flex-col gap-2">
              <NameStep state={onboardingState} actions={onboardingActions} />
              <LLMStep
                state={onboardingState}
                actions={onboardingActions}
                llmDescriptors={llmDescriptors}
                disabled={
                  onboardingState.currentStep !== OnboardingStep.LlmSetup
                }
              />
            </div>
          </div>
          <div className="w-1/2 shrink-0">
            <FinalStep />
          </div>
        </div>
      </div>
    </div>
  );
};

const OnboardingFlow = memo(OnboardingFlowInner);
export default OnboardingFlow;
