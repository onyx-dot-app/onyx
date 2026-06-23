import React from "react";
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
import { useTranslation } from "react-i18next";

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
    const { t } = useTranslation();
    const iconPercentage =
      STEP_CONFIG[onboardingState.currentStep].iconPercentage;
    const rawTitle = STEP_CONFIG[onboardingState.currentStep].title;
    const rawButtonText = STEP_CONFIG[onboardingState.currentStep].buttonText;

    let title = rawTitle;
    if (rawTitle === "Let's take a moment to get you set up.") {
      title = t("onboarding.setup_title", "Let's take a moment to get you set up.");
    } else if (rawTitle === "Almost there! Connect your models to start chatting.") {
      title = t("onboarding.connect_models_title", "Almost there! Connect your models to start chatting.");
    } else if (rawTitle === "You're all set, review the optional settings or click Finish Setup") {
      title = t("onboarding.complete_title", "You're all set, review the optional settings or click Finish Setup");
    }

    let stepButtonText = rawButtonText;
    if (rawButtonText === "Let's Go") {
      stepButtonText = t("onboarding.btn_lets_go", "Let's Go");
    } else if (rawButtonText === "Next") {
      stepButtonText = t("onboarding.btn_next", "Next");
    } else if (rawButtonText === "Finish Setup") {
      stepButtonText = t("onboarding.btn_finish_setup", "Finish Setup");
    }

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
          title={title}
          sizePreset="main-ui"
          variant="body"
          color="muted"
          padding="sm"
          rightChildren={
            stepButtonText ? (
              <Section flexDirection="row">
                {!isWelcomeStep && (
                  <Text as="p" text03 mainUiBody>
                    {t("onboarding.step_indicator", {
                      defaultValue: "Step {{current}} of {{total}}",
                      current: onboardingState.stepIndex,
                      total: onboardingState.totalSteps
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
