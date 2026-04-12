import React from "react";
import { useTranslations } from "next-intl";
import { STEP_CONFIG } from "@/sections/onboarding/constants";
import {
  OnboardingActions,
  OnboardingState,
  OnboardingStep,
} from "@/interfaces/onboarding";
import Text from "@/refresh-components/texts/Text";
import { Button } from "@opal/components";
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

const ONBOARDING_STEP_TITLE_KEYS: Record<OnboardingStep, string> = {
  [OnboardingStep.Welcome]: "onboarding.welcomeTitle",
  [OnboardingStep.Name]: "onboarding.welcomeTitle",
  [OnboardingStep.LlmSetup]: "onboarding.llmSetupTitle",
  [OnboardingStep.Complete]: "onboarding.completeTitle",
};

const ONBOARDING_STEP_BUTTON_KEYS: Record<OnboardingStep, string> = {
  [OnboardingStep.Welcome]: "onboarding.welcomeButton",
  [OnboardingStep.Name]: "onboarding.nextButton",
  [OnboardingStep.LlmSetup]: "onboarding.nextButton",
  [OnboardingStep.Complete]: "onboarding.finishSetupButton",
};

const OnboardingHeader = React.memo(
  ({
    state: onboardingState,
    actions: onboardingActions,
    handleHideOnboarding,
    handleFinishOnboarding,
  }: OnboardingHeaderProps) => {
    const t = useTranslations("chat");
    const iconPercentage =
      STEP_CONFIG[onboardingState.currentStep].iconPercentage;
    const stepTitle = t(ONBOARDING_STEP_TITLE_KEYS[onboardingState.currentStep]);
    const stepButtonText = t(ONBOARDING_STEP_BUTTON_KEYS[onboardingState.currentStep]);
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
          title={stepTitle}
          sizePreset="main-ui"
          variant="body"
          prominence="muted"
          paddingVariant="sm"
          rightChildren={
            stepButtonText ? (
              <Section flexDirection="row">
                {!isWelcomeStep && (
                  <Text as="p" text03 mainUiBody>
                    {t("onboarding.stepOf", {
                      current: onboardingState.stepIndex,
                      total: onboardingState.totalSteps,
                    })}
                  </Text>
                )}
                <Button
                  disabled={!onboardingState.isButtonActive}
                  onClick={handleButtonClick}
                >
                  {stepButtonText}
                </Button>
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
