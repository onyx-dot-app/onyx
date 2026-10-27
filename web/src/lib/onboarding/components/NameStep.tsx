"use client";

import React from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  IconContainer,
  InputTypeIn,
  SelectCard,
} from "@opal/components";
import {
  OnboardingState,
  OnboardingActions,
  OnboardingStep,
} from "@/lib/onboarding/types";
import { cn } from "@opal/utils";
import { SvgCheckCircle, SvgEdit, SvgUser } from "@opal/icons";
import { ContentAction, InputHorizontal, Section } from "@opal/layouts";
import { Hoverable } from "@opal/core";
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
    const { updateName, goToStep, setButtonActive, nextStep } =
      onboardingActions;

    const isActive = onboardingState.currentStep === OnboardingStep.Name;
    const containerClasses = cn(
      "flex items-center justify-between w-full p-3 bg-background-tint-00 rounded-16 border border-border-01"
    );

    const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter" && userName && userName.trim().length > 0) {
        e.preventDefault();
        nextStep();
      }
    };

    const handleEdit = () => {
      setButtonActive(true);
      goToStep(OnboardingStep.Name);
    };

    return isActive ? (
      <div
        className={containerClasses}
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
            placeholder={t("nameStep.input.placeholder")}
            value={userName || ""}
            onChange={(e) => updateName(e.target.value)}
            onKeyDown={handleKeyDown}
          />
        </InputHorizontal>
      </div>
    ) : (
      <Hoverable.Root group="nameStep" width="full">
        <SelectCard
          state="empty"
          padding={2}
          rounding={4}
          onClick={handleEdit}
          aria-label={t("nameStep.edit.ariaLabel")}
        >
          <div className="pl-1">
            <ContentAction
              icon={() => (
                <IconContainer
                  size="secondary"
                  avatar="user"
                  name={userName ?? ""}
                />
              )}
              title={userName ?? ""}
              sizePreset="main-ui"
              variant="section"
              padding={0}
              center
              rightChildren={
                <Section
                  flexDirection="row"
                  alignItems="center"
                  gap={1}
                  width="fit"
                  height="auto"
                >
                  <Hoverable.Item group="nameStep" variant="appear-on-hover">
                    <Button
                      prominence="tertiary"
                      size="md"
                      icon={SvgEdit}
                      tooltip={t("nameStep.edit.tooltip")}
                    />
                  </Hoverable.Item>
                  <Section padding={1} width="fit" height="auto">
                    <IconContainer
                      icon={({ className, ...props }) => (
                        <SvgCheckCircle
                          className={cn(className, "stroke-status-success-05")}
                          {...props}
                        />
                      )}
                    />
                  </Section>
                </Section>
              }
            />
          </div>
        </SelectCard>
      </Hoverable.Root>
    );
  }
);
NameStep.displayName = "NameStep";

export default NameStep;
