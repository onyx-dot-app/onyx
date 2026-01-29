"use client";

import { FiInfo } from "react-icons/fi";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import {
  WorkArea,
  Level,
  WORK_AREA_OPTIONS,
  LEVEL_OPTIONS,
  WORK_AREAS_REQUIRING_LEVEL,
} from "@/app/craft/onboarding/constants";

interface SelectableButtonProps {
  selected: boolean;
  onClick: () => void;
  children: React.ReactNode;
  subtext?: string;
  disabled?: boolean;
  tooltip?: string;
}

function SelectableButton({
  selected,
  onClick,
  children,
  subtext,
  disabled,
  tooltip,
}: SelectableButtonProps) {
  const button = (
    <div className="flex flex-col items-center gap-1">
      <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        className={cn(
          "w-full px-6 py-3 rounded-12 border transition-colors",
          disabled && "opacity-50 cursor-not-allowed",
          selected
            ? "border-action-link-05 bg-action-link-01 text-action-text-link-05"
            : "border-border-01 bg-background-tint-00 text-text-04 hover:bg-background-tint-01"
        )}
      >
        <Text mainUiAction>{children}</Text>
      </button>
      {subtext && (
        <Text figureSmallLabel text02>
          {subtext}
        </Text>
      )}
    </div>
  );

  if (tooltip) {
    return <SimpleTooltip tooltip={tooltip}>{button}</SimpleTooltip>;
  }

  return button;
}

interface OnboardingUserInfoProps {
  firstName: string;
  lastName: string;
  workArea: WorkArea | undefined;
  level: Level | undefined;
  onFirstNameChange: (value: string) => void;
  onLastNameChange: (value: string) => void;
  onWorkAreaChange: (value: WorkArea | undefined) => void;
  onLevelChange: (value: Level | undefined) => void;
}

export default function OnboardingUserInfo({
  firstName,
  lastName,
  workArea,
  level,
  onFirstNameChange,
  onLastNameChange,
  onWorkAreaChange,
  onLevelChange,
}: OnboardingUserInfoProps) {
  const requiresLevel =
    workArea !== undefined && WORK_AREAS_REQUIRING_LEVEL.includes(workArea);

  return (
    <div className="flex-1 flex flex-col gap-6">
      {/* Header */}
      <div className="flex items-center justify-center gap-2">
        <SimpleTooltip
          tooltip="We use this information to personalize your demo data and examples."
          side="bottom"
        >
          <button
            type="button"
            className="text-text-02 hover:text-text-03 transition-colors"
          >
            <FiInfo size={16} className="text-text-03" />
          </button>
        </SimpleTooltip>
        <Text headingH2 text05>
          Tell us about yourself
        </Text>
      </div>

      <div className="flex-1 flex flex-col gap-8 justify-center">
        {/* Name inputs */}
        <div className="flex justify-center">
          <div className="grid grid-cols-2 gap-4 w-full max-w-md">
            <div className="flex flex-col gap-1.5">
              <Text secondaryBody text03>
                First name
              </Text>
              <input
                type="text"
                value={firstName}
                onChange={(e) => onFirstNameChange(e.target.value)}
                placeholder="Steven"
                className="w-full px-3 py-2 rounded-08 input-normal text-text-04 placeholder:text-text-02 focus:outline-none"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Text secondaryBody text03>
                Last name
              </Text>
              <input
                type="text"
                value={lastName}
                onChange={(e) => onLastNameChange(e.target.value)}
                placeholder="Alexson"
                className="w-full px-3 py-2 rounded-08 input-normal text-text-04 placeholder:text-text-02 focus:outline-none"
              />
            </div>
          </div>
        </div>

        {/* Work area */}
        <div className="flex flex-col gap-3 items-center">
          <Text mainUiBody text04>
            What do you do?
          </Text>
          <div className="grid grid-cols-3 gap-3 w-full">
            {WORK_AREA_OPTIONS.map((option) => (
              <SelectableButton
                key={option.value}
                selected={workArea === option.value}
                onClick={() => onWorkAreaChange(option.value)}
              >
                {option.label}
              </SelectableButton>
            ))}
          </div>
        </div>

        {/* Level */}
        <div className="flex flex-col gap-3 items-center">
          <Text mainUiBody text04>
            Level{" "}
            {requiresLevel && <span className="text-status-error-05">*</span>}
          </Text>
          <div className="flex justify-center gap-3 w-full">
            <div className="grid grid-cols-2 gap-3 w-2/3">
              {LEVEL_OPTIONS.map((option) => (
                <SelectableButton
                  key={option.value}
                  selected={level === option.value}
                  onClick={() =>
                    onLevelChange(
                      level === option.value ? undefined : option.value
                    )
                  }
                >
                  {option.label}
                </SelectableButton>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
