import React, { memo } from "react";
import { STEP_CONFIG } from "../constants";
import { useOnboardingState } from "../useOnboardingState";
import Text from "@/refresh-components/texts/Text";
import SvgStep1 from "@/icons/step1";
import SvgFold from "@/icons/fold";
import Button from "@/refresh-components/buttons/Button";
import IconButton from "@/refresh-components/buttons/IconButton";

const OnboardingHeaderInner = () => {
  const { state: onboardingState } = useOnboardingState();
  return (
    <div className="flex items-center justify-between w-full max-w-[800px] min-h-11 py-spacing-inline pl-padding-button pr-spacing-interline bg-background-tint-00 rounded-16 shadow-01">
      <div className="flex items-center gap-spacing-inline">
        <SvgStep1 className="w-4 h-4 stroke-background-neutral-inverted-00" />
        <Text text03 mainUiBody>
          {STEP_CONFIG[onboardingState.currentStep].title}
        </Text>
      </div>
      <div className="flex items-center gap-padding-button">
        <Text text03 mainUiBody>
          Step{onboardingState.stepIndex} of {onboardingState.totalSteps}
        </Text>
        <Button onClick={() => {}}>Next</Button>
        <IconButton internal icon={SvgFold} />
      </div>
    </div>
  );
};

const OnboardingHeader = memo(OnboardingHeaderInner);
export default OnboardingHeader;
