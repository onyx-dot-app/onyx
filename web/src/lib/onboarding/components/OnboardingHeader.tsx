"use client";

import { createContext, memo, useContext, useState } from "react";
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
import {
  Button,
  Card,
  IconContainer,
  Presence,
  Text,
  type PresenceSide,
} from "@opal/components";
import { SvgChevronLeft, SvgProgressCircle, SvgX } from "@opal/icons";
import { Section } from "@opal/layouts";
import type { IconProps } from "@opal/types";

// The progress icon is one stable component that reads its value from
// context. An inline icon function would remount the svg on each render, and
// the pie would not animate.
const ProgressContext = createContext(0);

function ProgressIcon(props: IconProps) {
  return <SvgProgressCircle value={useContext(ProgressContext)} {...props} />;
}

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
  // The prompt comes in from the end going forward, and from the start going
  // back.
  const [promptStep, setPromptStep] = useState(onboardingState.currentStep);
  const [promptFrom, setPromptFrom] = useState<PresenceSide>("end");
  if (onboardingState.currentStep !== promptStep) {
    setPromptFrom(
      STEP_CONFIG[onboardingState.currentStep].index >
        STEP_CONFIG[promptStep].index
        ? "end"
        : "start"
    );
    setPromptStep(onboardingState.currentStep);
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
      <Section
        flexDirection="row"
        justifyContent="between"
        alignItems="center"
        gap={2}
        height="fit"
      >
        {/* The prompt: the step's progress and one sentence, which comes in
            again on each step. */}
        <Section
          flexDirection="row"
          justifyContent="start"
          alignItems="center"
          gap={1}
          padding={1}
          height="fit"
        >
          <ProgressContext value={progress}>
            <IconContainer icon={ProgressIcon} />
          </ProgressContext>
          <Presence
            key={onboardingState.currentStep}
            from={promptFrom}
            width="fit"
          >
            <Text font="main-ui-body" color="text-03">
              {t(STEP_CONFIG[onboardingState.currentStep].titleKey)}
            </Text>
          </Presence>
        </Section>
        {stepButtonText ? (
          <Section flexDirection="row" justifyContent="end" width="fit">
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
        )}
      </Section>
    </Card>
  );
}

export default memo(OnboardingHeader);
