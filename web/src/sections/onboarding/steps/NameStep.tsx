"use client";

import React, { useRef } from "react";
import Text from "@/refresh-components/texts/Text";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import {
  OnboardingState,
  OnboardingActions,
  OnboardingStep,
} from "@/interfaces/onboarding";
import InputAvatar from "@/refresh-components/inputs/InputAvatar";
import { cn } from "@opal/utils";
import IconButton from "@/refresh-components/buttons/IconButton";
import { SvgCheckCircle, SvgEdit, SvgUser } from "@opal/icons";
import { ContentAction } from "@opal/layouts";
import { Hoverable } from "@opal/core";

export interface NameStepProps {
  state: OnboardingState;
  actions: OnboardingActions;
}

const NameStep = React.memo(
  ({ state: onboardingState, actions: onboardingActions }: NameStepProps) => {
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

    const inputRef = useRef<HTMLInputElement>(null);
    return isActive ? (
      <div
        className={containerClasses}
        onClick={() => inputRef.current?.focus()}
        role="group"
        aria-label="onboarding-name-step"
      >
        <ContentAction
          icon={SvgUser}
          title="What should Onyx call you?"
          description="We will display this name in the app."
          sizePreset="main-ui"
          variant="section"
          padding="fit"
          rightChildren={
            <InputTypeIn
              ref={inputRef}
              placeholder="Your name"
              value={userName || ""}
              onChange={(e) => updateName(e.target.value)}
              onKeyDown={handleKeyDown}
              className="max-w-60"
            />
          }
        />
      </div>
    ) : (
      <Hoverable.Root group="nameStep" width="full">
        <div
          className={containerClasses}
          onClick={() => {
            setButtonActive(true);
            goToStep(OnboardingStep.Name);
          }}
          aria-label="Edit display name"
          role="button"
          tabIndex={0}
        >
          <div
            className={cn("flex items-center gap-1", !isActive && "opacity-50")}
          >
            <InputAvatar
              className={cn(
                "flex items-center justify-center bg-background-neutral-inverted-00",
                "w-5 h-5"
              )}
            >
              <Text as="p" inverted secondaryBody>
                {userName?.[0]?.toUpperCase()}
              </Text>
            </InputAvatar>
            <Text as="p" text04 mainUiAction>
              {userName}
            </Text>
          </div>
          <div className="p-1 flex items-center gap-1">
            {/* TODO(@raunakab): migrate to opal Button once className/iconClassName is resolved */}
            <Hoverable.Item group="nameStep" variant="opacity-on-hover">
              <IconButton internal icon={SvgEdit} tooltip="Edit" />
            </Hoverable.Item>
            <SvgCheckCircle
              className={cn(
                "w-4 h-4 stroke-status-success-05",
                !isActive && "opacity-50"
              )}
            />
          </div>
        </div>
      </Hoverable.Root>
    );
  }
);
NameStep.displayName = "NameStep";

export default NameStep;
