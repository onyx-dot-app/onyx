"use client";

import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import {
  WorkArea,
  Level,
  WORK_AREA_OPTIONS,
  LEVEL_OPTIONS,
  WORK_AREAS_REQUIRING_LEVEL,
  PERSONA_MAPPING,
  DEMO_COMPANY_NAME,
  getPositionText,
} from "@/app/craft/onboarding/constants";

interface SelectableButtonProps {
  selected: boolean;
  onClick: () => void;
  children: React.ReactNode;
  subtext?: string;
  disabled?: boolean;
}

function SelectableButton({
  selected,
  onClick,
  children,
  subtext,
  disabled,
}: SelectableButtonProps) {
  return (
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
  firstName: _firstName,
  lastName: _lastName,
  workArea,
  level,
  onFirstNameChange: _onFirstNameChange,
  onLastNameChange: _onLastNameChange,
  onWorkAreaChange,
  onLevelChange,
}: OnboardingUserInfoProps) {
  const requiresLevel =
    workArea !== undefined && WORK_AREAS_REQUIRING_LEVEL.includes(workArea);

  // Get persona info for preview
  const selectedLevel = level ?? Level.IC;
  const personaInfo =
    workArea !== undefined ? PERSONA_MAPPING[workArea]?.[selectedLevel] : null;
  const positionText =
    workArea !== undefined ? getPositionText(workArea, level) : null;

  return (
    <div className="flex-1 flex flex-col gap-6">
      {/* Header */}
      <div className="flex flex-col items-center gap-3">
        <Text headingH2 text05>
          Demo Data Configuration
        </Text>
      </div>

      <div className="flex-1 flex flex-col gap-8 justify-center">
        {/* Name inputs - commented out for now, can be re-enabled later
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
        */}

        <Text mainUiBody text04 className="text-center">
          While you wait for your data to sync, try out our simulated demo
          dataset! <br />
          The simulated data will adapt to your role and level choices below.
        </Text>

        {/* Work area */}
        <div className="flex flex-col gap-3 items-center">
          <Text mainUiBody text04>
            Select your role:
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

        {/* Persona preview - always reserve space to prevent layout shift */}
        <div className="flex justify-center min-h-[1.5rem]">
          {personaInfo && positionText && (
            <Text mainContentBody text03 className="text-center">
              You will play the role of {positionText} named {personaInfo.name}{" "}
              working at <br />
              {DEMO_COMPANY_NAME}
            </Text>
          )}
        </div>
      </div>
    </div>
  );
}
