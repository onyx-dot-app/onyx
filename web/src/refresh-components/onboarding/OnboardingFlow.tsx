import React, { memo } from "react";
import OnboardingHeader from "./components/OnboardingHeader";
import NameStep from "./steps/NameStep";
import LLMStep from "./steps/LLMStep";
import FinalStep from "./steps/FinalStep";

const OnboardingFlowInner = () => {
  return (
    <div className="flex flex-col items-center justify-center w-full max-w-[800px] gap-spacing-interline mb-spacing-paragraph">
      <OnboardingHeader />
      {/* <NameStep/>
            <LLMStep/> */}
      <FinalStep />
    </div>
  );
};

const OnboardingFlow = memo(OnboardingFlowInner);
export default OnboardingFlow;
