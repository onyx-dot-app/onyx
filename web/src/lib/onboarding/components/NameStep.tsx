"use client";

import React, { useEffect, useRef } from "react";
import { useTranslations } from "next-intl";
import { Card, InputTypeIn } from "@opal/components";
import { OnboardingState, OnboardingActions } from "@/lib/onboarding/types";
import { SvgUser } from "@opal/icons";
import { InputHorizontal } from "@opal/layouts";
import { useSettings } from "@/lib/settings/hooks";

export interface NameStepProps {
  state: OnboardingState;
  actions: OnboardingActions;
}

const NameStep = React.memo(
  ({ state: onboardingState, actions: onboardingActions }: NameStepProps) => {
    const t = useTranslations("onboarding");
    const { appName } = useSettings();
    const { userName } = onboardingState.data;
    const { updateName, nextStep } = onboardingActions;

    // The step's only control: ready to type as soon as the step appears.
    const inputRef = useRef<HTMLInputElement>(null);
    useEffect(() => {
      inputRef.current?.focus();
    }, []);

    const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter" && userName && userName.trim().length > 0) {
        e.preventDefault();
        nextStep();
      }
    };

    return (
      <Card
        border="solid"
        padding={3}
        rounding={4}
        role="group"
        aria-label="onboarding-name-step"
      >
        <InputHorizontal
          withLabel
          fillInput
          icon={SvgUser}
          title={t("nameStep.title", { appName })}
          description={t("nameStep.description")}
        >
          <InputTypeIn
            ref={inputRef}
            placeholder={t("nameStep.input.placeholder")}
            value={userName || ""}
            onChange={(e) => updateName(e.target.value)}
            onKeyDown={handleKeyDown}
          />
        </InputHorizontal>
      </Card>
    );
  }
);
NameStep.displayName = "NameStep";

export default NameStep;
