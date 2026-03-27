import React from "react";
import { STEP_CONFIG } from "@/sections/onboarding/constants";
import {
  OnboardingActions,
  OnboardingState,
  OnboardingStep,
} from "@/interfaces/onboarding";
import { Button, Text } from "@opal/components";
import { Disabled } from "@opal/core";
import { SvgProgressCircle, SvgX } from "@opal/icons";
import { Card } from "@/refresh-components/cards";
import { Section } from "@/layouts/general-layouts";
import { ContentAction } from "@opal/layouts";

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
      <Card padding={0.5} data-label="onboarding-header">
        <ContentAction
          icon={(props) => (
            <SvgProgressCircle value={iconPercentage} {...props} />
          )}
          title={STEP_CONFIG[onboardingState.currentStep].title}
          sizePreset="main-ui"
          variant="body"
          prominence="muted"
          paddingVariant="sm"
          rightChildren={
            stepButtonText ? (
              <Section flexDirection="row">
                {!isWelcomeStep && (
                  <Text as="p" color="text-03">
                    {`Step ${onboardingState.stepIndex} of ${onboardingState.totalSteps}`}
                  </Text>
                )}
                <Disabled disabled={!onboardingState.isButtonActive}>
                  <Button onClick={handleButtonClick}>{stepButtonText}</Button>
                </Disabled>
              </Section>
            ) : (
              <Button
                prominence="tertiary"
                size="sm"
                icon={SvgX}
                onClick={handleHideOnboarding}
              />
            )
          }
        />
      </Card>
    );
  }
);
OnboardingHeader.displayName = "OnboardingHeader";

export default OnboardingHeader;
