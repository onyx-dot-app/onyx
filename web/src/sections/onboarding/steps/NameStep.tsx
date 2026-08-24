"use client";

import React, { useRef } from "react";
import Text from "@/refresh-components/texts/Text";
import { Button, InputTypeIn } from "@opal/components";
import {
  OnboardingState,
  OnboardingActions,
  OnboardingStep,
} from "@/interfaces/onboarding";
import InputAvatar from "@/refresh-components/inputs/InputAvatar";
import { cn, clickOnKeyDown } from "@opal/utils";
import { SvgCheckCircle, SvgEdit, SvgUser } from "@opal/icons";
import { InputHorizontal } from "@opal/layouts";
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
        {/* Pointer convenience only — the input is already keyboard reachable. */}
        <div
          role="presentation"
          className="contents"
          onClick={() => inputRef.current?.focus()}
        >
          <InputHorizontal
            responsive
            icon={SvgUser}
            title="What should Onyx call you?"
            description="We will display this name in the app."
          >
            <InputTypeIn
              ref={inputRef}
              placeholder="Your name"
              value={userName || ""}
              onChange={(e) => updateName(e.target.value)}
              onKeyDown={handleKeyDown}
            />
          </InputHorizontal>
        </div>
      </div>
    ) : (
      <Hoverable.Root group="nameStep" width="full">
        <div
          className={containerClasses}
          onClick={handleEdit}
          onKeyDown={clickOnKeyDown(handleEdit)}
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
            <Hoverable.Item group="nameStep" variant="appear-on-hover">
              <Button
                prominence="internal"
                size="sm"
                icon={SvgEdit}
                tooltip="Edit"
              />
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
