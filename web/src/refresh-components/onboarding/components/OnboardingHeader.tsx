import { memo } from "react";
import { STEP_CONFIG } from "../constants";
import { OnboardingActions, OnboardingState } from "../types";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgX from "@/icons/x";
import SvgCheckCircle from "@/icons/check-circle";
import { OnboardingStep } from "../types";
import ProgressSteps from "@/refresh-components/inputs/ProgressSteps";

type OnboardingHeaderProps = {
  state: OnboardingState;
  actions: OnboardingActions;
  handleHideOnboarding: () => void;
};

const OnboardingHeaderInner = ({
  state: onboardingState,
  actions: onboardingActions,
  handleHideOnboarding,
}: OnboardingHeaderProps) => {
  const iconPercentage =
    STEP_CONFIG[onboardingState.currentStep].iconPercentage;
  const stepButtonText = STEP_CONFIG[onboardingState.currentStep].buttonText;
  const isWelcomeStep = onboardingState.currentStep === OnboardingStep.Welcome;
  const isCompleteStep =
    onboardingState.currentStep === OnboardingStep.Complete;

  const handleButtonClick = () => {
    if (isCompleteStep) {
      handleHideOnboarding();
    } else {
      onboardingActions.nextStep();
    }
  };

  return (
    <div className="flex items-center justify-between w-full max-w-[800px] min-h-11 py-1 pl-3 pr-2 bg-background-tint-00 rounded-16 shadow-01">
      <div className="flex items-center gap-1">
        {iconPercentage != null ? (
          <ProgressSteps value={iconPercentage} />
        ) : (
          <SvgCheckCircle className="w-4 h-4 stroke-status-success-05" />
        )}
        <Text text03 mainUiBody>
          {STEP_CONFIG[onboardingState.currentStep].title}
        </Text>
      </div>
      <div className="flex items-center gap-3">
        {stepButtonText ? (
          <>
            {!isWelcomeStep && (
              <Text text03 mainUiBody>
                Step {onboardingState.stepIndex} of {onboardingState.totalSteps}
              </Text>
            )}
            <Button
              onClick={handleButtonClick}
              disabled={!onboardingState.isButtonActive}
            >
              {stepButtonText}
            </Button>
          </>
        ) : (
          <IconButton internal icon={SvgX} onClick={handleHideOnboarding} />
        )}
      </div>
    </div>
  );
};

const OnboardingHeader = memo(OnboardingHeaderInner);
export default OnboardingHeader;
