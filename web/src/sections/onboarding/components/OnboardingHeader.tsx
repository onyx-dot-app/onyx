"use client";

import React from "react";
import { useTranslations } from "next-intl";
import { STEP_CONFIG } from "@/sections/onboarding/constants";
import {
  OnboardingActions,
  OnboardingState,
  OnboardingStep,
} from "@/interfaces/onboarding";
import Text from "@/refresh-components/texts/Text";
import { Button, Card } from "@opal/components";
import { SvgProgressCircle, SvgX } from "@opal/icons";
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
    const t = useTranslations("onboarding");
    const iconPercentage =
      STEP_CONFIG[onboardingState.currentStep].iconPercentage;
    const stepButtonText = t(
      STEP_CONFIG[onboardingState.currentStep].buttonTextKey
    );
    const isWelcomeStep =
      onboardingState.currentStep === OnboardingStep.Welcome;
    const isCompleteStep =
      onboardingState.currentStep === OnboardingStep.Complete;

    function handleButtonClick() {
      if (isCompleteStep) handleFinishOnboarding();
      else onboardingActions.nextStep();
    }

    return (
      <Card
        border="solid"
        padding={2}
        data-label="onboarding-header"
        rounding={4}
      >
        <Section alignItems="start" height="fit">
          <ContentAction
            icon={(props) => (
              <SvgProgressCircle value={iconPercentage} {...props} />
            )}
            title={t(STEP_CONFIG[onboardingState.currentStep].titleKey)}
            sizePreset="main-ui"
            variant="body"
            color="muted"
            padding={1}
            rightChildren={
              stepButtonText ? (
                <Section flexDirection="row">
                  {!isWelcomeStep && (
                    <Text as="p" text03 mainUiBody>
                      {t("header.progress.label", {
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
        </Section>
      </Card>
    );
  }
);
OnboardingHeader.displayName = "OnboardingHeader";

export default OnboardingHeader;
