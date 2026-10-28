"use client";

import { memo, useState } from "react";
import { useTranslations } from "next-intl";
import {
  STEP_CONFIG,
  STEP_NAVIGATION,
  TOTAL_STEPS,
  stepNumber,
  stepProgress,
} from "@/lib/onboarding/constants";
import {
  OnboardingActions,
  OnboardingState,
  OnboardingStep,
} from "@/lib/onboarding/types";
import { Button, Card, Presence, Text } from "@opal/components";
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
  const progress = stepProgress(onboardingState.currentStep);
  const currentNumber = stepNumber(onboardingState.currentStep);
  const isPostStep = onboardingState.currentStep === OnboardingStep.PostStep;
  // The main button reads Next on every step but the post-step.
  const stepButtonText = isPostStep
    ? t("header.finishButton.label")
    : t("header.nextButton.label");
  // The counter shows on the numbered steps only. While it fades out on the
  // pre-step or post-step, it keeps the last number it showed.
  const [counterNumber, setCounterNumber] = useState(currentNumber ?? 1);
  if (currentNumber !== null && currentNumber !== counterNumber) {
    setCounterNumber(currentNumber);
  }
  const hasPreviousStep =
    STEP_NAVIGATION[onboardingState.currentStep].prev !== undefined;

  function handleButtonClick() {
    if (isPostStep) handleFinishOnboarding();
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
          icon={(props) => <SvgProgressCircle value={progress} {...props} />}
          title={t(STEP_CONFIG[onboardingState.currentStep].titleKey)}
          // A new prompt fades in on each step.
          titleKey={onboardingState.currentStep}
          sizePreset="main-ui"
          variant="body"
          color="muted"
          padding={1}
          center
          rightChildren={
            stepButtonText ? (
              <Section flexDirection="row">
                {/* The step counter shows on the numbered steps only. */}
                <Presence show={currentNumber !== null} from="end" width="fit">
                  <Text as="p" font="main-ui-body" color="text-03">
                    {t("header.progress.label", {
                      current: counterNumber,
                      total: TOTAL_STEPS,
                    })}
                  </Text>
                </Presence>
                <Section flexDirection="row" gap={1} width="fit">
                  <Presence show={hasPreviousStep} from="end" width="fit">
                    <Button
                      prominence="secondary"
                      icon={SvgChevronLeft}
                      tooltip={tCommon("backButton.label")}
                      aria-label={tCommon("backButton.label")}
                      onClick={onboardingActions.prevStep}
                    />
                  </Presence>
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
