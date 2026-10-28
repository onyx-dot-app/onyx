"use client";

import { memo } from "react";
import { useTranslations } from "next-intl";
import { STEP_CONFIG, STEP_NAVIGATION } from "@/lib/onboarding/constants";
import {
  OnboardingActions,
  OnboardingState,
  OnboardingStep,
} from "@/lib/onboarding/types";
import { Button, Card, Text } from "@opal/components";
import { SvgChevronLeft, SvgProgressCircle, SvgX } from "@opal/icons";
import { ContentAction, Section } from "@opal/layouts";

interface OnboardingHeaderProps {
  state: OnboardingState;
  actions: OnboardingActions;
  handleHideOnboarding: () => void;
  handleFinishOnboarding: () => void;
}

function OnboardingHeader({
  state: onboardingState,
  actions: onboardingActions,
  handleHideOnboarding,
  handleFinishOnboarding,
}: OnboardingHeaderProps) {
  const t = useTranslations("onboarding");
  const tCommon = useTranslations("common");
  const iconPercentage =
    STEP_CONFIG[onboardingState.currentStep].iconPercentage;
  const isWelcomeStep = onboardingState.currentStep === OnboardingStep.Welcome;
  const isCompleteStep =
    onboardingState.currentStep === OnboardingStep.Complete;
  // The main button reads Next on every step but the last.
  const stepButtonText = isCompleteStep
    ? t("header.finishButton.label")
    : t("header.nextButton.label");
  const hasPreviousStep =
    STEP_NAVIGATION[onboardingState.currentStep].prev !== undefined;

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
          center
          rightChildren={
            stepButtonText ? (
              <Section flexDirection="row">
                {!isWelcomeStep && (
                  <Text as="p" font="main-ui-body" color="text-03">
                    {t("header.progress.label", {
                      current: onboardingState.stepIndex,
                      total: onboardingState.totalSteps,
                    })}
                  </Text>
                )}
                <Section flexDirection="row" gap={1} width="fit">
                  {hasPreviousStep && (
                    <Button
                      prominence="secondary"
                      icon={SvgChevronLeft}
                      tooltip={tCommon("backButton.label")}
                      aria-label={tCommon("backButton.label")}
                      onClick={onboardingActions.prevStep}
                    />
                  )}
                  <Button
                    disabled={!onboardingState.isButtonActive}
                    onClick={handleButtonClick}
                  >
                    {stepButtonText}
                  </Button>
                </Section>
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

export default memo(OnboardingHeader);
