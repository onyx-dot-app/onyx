import React, { memo } from "react";
import { STEP_CONFIG } from "../constants";
import { OnboardingActions, OnboardingState } from "../types";
import Text from "@/refresh-components/texts/Text";
import SvgFold from "@/icons/fold";
import Button from "@/refresh-components/buttons/Button";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgX from "@/icons/x";
import SvgCheckCircle from "@/icons/check-circle";

type OnboardingHeaderProps = {
  state: OnboardingState;
  actions: OnboardingActions;
};

const OnboardingHeaderInner = ({
  state: onboardingState,
  actions: onboardingActions,
}: OnboardingHeaderProps) => {
  const StepIcon = STEP_CONFIG[onboardingState.currentStep].icon;
  const stepButtonText = STEP_CONFIG[onboardingState.currentStep].buttonText;
  return (
    <div className="flex items-center justify-between w-full max-w-[800px] min-h-11 py-spacing-inline pl-padding-button pr-spacing-interline bg-background-tint-00 rounded-16 shadow-01">
      <div className="flex items-center gap-spacing-inline">
        {StepIcon ? (
          <StepIcon className="w-4 h-4 stroke-background-neutral-inverted-00" />
        ) : (
          <SvgCheckCircle className="w-4 h-4 stroke-status-success-05" />
        )}
        <Text text03 mainUiBody>
          {STEP_CONFIG[onboardingState.currentStep].title}
        </Text>
      </div>
      <div className="flex items-center gap-padding-button">
        {stepButtonText ? (
          <>
            <Text text03 mainUiBody>
              Step {onboardingState.stepIndex} of {onboardingState.totalSteps}
            </Text>
            <Button
              onClick={onboardingActions.nextStep}
              disabled={!onboardingState.isButtonActive}
            >
              {stepButtonText}
            </Button>
            <IconButton internal icon={SvgFold} />
          </>
        ) : (
          <IconButton internal icon={SvgX} onClick={() => {}} />
        )}
      </div>
    </div>
  );
};

const OnboardingHeader = memo(OnboardingHeaderInner);
export default OnboardingHeader;
