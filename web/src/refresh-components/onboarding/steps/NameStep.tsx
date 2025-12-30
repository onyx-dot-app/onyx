import React, { memo, useRef } from "react";
import Text from "@/refresh-components/texts/Text";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import { OnboardingState, OnboardingActions, OnboardingStep } from "../types";
import InputAvatar from "@/refresh-components/inputs/InputAvatar";
import { cn } from "@/lib/utils";
import IconButton from "@/refresh-components/buttons/IconButton";
import { SvgCheckCircle, SvgEdit, SvgUser } from "@opal/icons";
type NameStepProps = {
  state: OnboardingState;
  actions: OnboardingActions;
};

const NameStepInner = ({
  state: onboardingState,
  actions: onboardingActions,
}: NameStepProps) => {
  const { userName } = onboardingState.data;
  const { updateName, goToStep, setButtonActive, nextStep } = onboardingActions;

  const isActive = onboardingState.currentStep === OnboardingStep.Name;
  const containerClasses = cn(
    "flex items-center justify-between w-full max-w-[800px] p-3 bg-background-tint-00 rounded-16 border border-border-01"
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
    >
      <div className="flex items-center gap-1 h-full">
        <div className="h-full p-0.5">
          <SvgUser className="w-4 h-4 stroke-text-03" />
        </div>
        <div>
          <Text as="p" text04 mainUiAction>
            What should Onyx call you?
          </Text>
          <Text as="p" text03 secondaryBody>
            We will display this name in the app.
          </Text>
        </div>
      </div>
      <InputTypeIn
        ref={inputRef}
        placeholder="Your name"
        value={userName || ""}
        onChange={(e) => updateName(e.target.value)}
        onKeyDown={handleKeyDown}
        className="w-[26%] min-w-40"
      />
    </div>
  ) : (
    <div
      className={cn(containerClasses, "group")}
      onClick={() => {
        setButtonActive(true);
        goToStep(OnboardingStep.Name);
      }}
      aria-label="Edit display name"
      role="button"
      tabIndex={0}
    >
      <div className={cn("flex items-center gap-1", !isActive && "opacity-50")}>
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
        <IconButton
          internal
          icon={SvgEdit}
          tooltip="Edit"
          className="opacity-0 group-hover:opacity-100 transition-opacity"
        />
        <SvgCheckCircle
          className={cn(
            "w-4 h-4 stroke-status-success-05",
            !isActive && "opacity-50"
          )}
        />
      </div>
    </div>
  );
};

const NameStep = memo(NameStepInner);
export default NameStep;
