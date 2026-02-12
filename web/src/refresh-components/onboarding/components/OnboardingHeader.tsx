import React from "react";
import { STEP_CONFIG } from "@/refresh-components/onboarding/constants";
import {
  OnboardingActions,
  OnboardingState,
  OnboardingStep,
} from "@/refresh-components/onboarding/types";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import { Button as OpalButton } from "@opal/components";
import { SvgProgressCircle, SvgX } from "@opal/icons";
import { Card } from "@/refresh-components/cards";
import { LineItemLayout, Section } from "@/layouts/general-layouts";

interface OnboardingHeaderProps {
  state: OnboardingState;
  actions: OnboardingActions;
  handleHideOnboarding: () => void;
  handleFinishOnboarding: () => void;
}
const OnboardingHeader = React.memo(
  ({
    state: onboardingState,
    actions: onboardingActions,
    handleHideOnboarding,
    handleFinishOnboarding,
  }: OnboardingHeaderProps) => {
    const iconPercentage =
      STEP_CONFIG[onboardingState.currentStep].iconPercentage;
    const stepButtonText = STEP_CONFIG[onboardingState.currentStep].buttonText;
    const isWelcomeStep =
      onboardingState.currentStep === OnboardingStep.Welcome;
    const isCompleteStep =
      onboardingState.currentStep === OnboardingStep.Complete;

    function handleButtonClick() {
      if (isCompleteStep) handleFinishOnboarding();
      else onboardingActions.nextStep();
    }

    return (
      <Card padding={0.5}>
        <LineItemLayout
          icon={(props) => (
            <SvgProgressCircle value={iconPercentage} {...props} />
          )}
          title={STEP_CONFIG[onboardingState.currentStep].title}
          rightChildren={
            stepButtonText ? (
              <Section flexDirection="row">
                {!isWelcomeStep && (
                  <Text as="p" text03 mainUiBody>
                    Step {onboardingState.stepIndex} of{" "}
                    {onboardingState.totalSteps}
                  </Text>
                )}
                <Button
                  onClick={handleButtonClick}
                  disabled={!onboardingState.isButtonActive}
                >
                  {stepButtonText}
                </Button>
              </Section>
            ) : (
              <OpalButton
                prominence="tertiary"
                size="sm"
                icon={SvgX}
                onClick={handleHideOnboarding}
              />
            )
          }
          variant="tertiary-muted"
          reducedPadding
          center
        />
      </Card>
    );
  }
);
OnboardingHeader.displayName = "OnboardingHeader";

export default OnboardingHeader;
