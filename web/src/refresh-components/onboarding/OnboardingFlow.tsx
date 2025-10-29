import React, { memo, useEffect } from "react";
import OnboardingHeader from "./components/OnboardingHeader";
import NameStep from "./steps/NameStep";
import LLMStep from "./steps/LLMStep";
import FinalStep from "./steps/FinalStep";
import { useOnboardingState } from "./useOnboardingState";
import { OnboardingStep } from "./types";

const OnboardingFlowInner = () => {
  const {
    state: onboardingState,
    actions: onboardingActions,
    llmDescriptors,
  } = useOnboardingState();

  return (
    <div className="flex flex-col items-center justify-center w-full max-w-[800px] gap-2 mb-4">
      <OnboardingHeader state={onboardingState} actions={onboardingActions} />
      <div className="relative w-full overflow-hidden">
        <div
          className={
            `flex w-[200%] transition-transform duration-300 ease-out ` +
            (onboardingState.currentStep === OnboardingStep.Complete
              ? "-translate-x-1/2"
              : "translate-x-0")
          }
        >
          <div className="w-1/2 shrink-0 pr-2">
            <div className="flex flex-col gap-2">
              <NameStep state={onboardingState} actions={onboardingActions} />
              <LLMStep
                state={onboardingState}
                actions={onboardingActions}
                llmDescriptors={llmDescriptors}
              />
            </div>
          </div>
          <div className="w-1/2 shrink-0 pl-2">
            <FinalStep />
          </div>
        </div>
      </div>
    </div>
  );
};

const OnboardingFlow = memo(OnboardingFlowInner);
export default OnboardingFlow;
