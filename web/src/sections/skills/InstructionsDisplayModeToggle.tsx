"use client";

import { Tooltip } from "@opal/components";
import { SvgCode, SvgEye } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import { cn } from "@opal/utils";

export type InstructionsDisplayMode = "rendered" | "raw";

const OPTIONS: {
  value: InstructionsDisplayMode;
  label: string;
  icon: IconFunctionComponent;
}[] = [
  { value: "rendered", label: "Rendered markdown", icon: SvgEye },
  { value: "raw", label: "Raw markdown", icon: SvgCode },
];

interface InstructionsDisplayModeToggleProps {
  value: InstructionsDisplayMode;
  onChange: (value: InstructionsDisplayMode) => void;
}

export default function InstructionsDisplayModeToggle({
  value,
  onChange,
}: InstructionsDisplayModeToggleProps) {
  return (
    <div
      role="group"
      className="inline-flex shrink-0 rounded-08 border border-border-01 bg-background-tint-01 p-0.5"
      aria-label="Instruction display mode"
    >
      {OPTIONS.map((option) => {
        const isSelected = option.value === value;
        const Icon = option.icon;
        return (
          <Tooltip key={option.value} tooltip={option.label} side="top">
            <button
              type="button"
              aria-label={option.label}
              aria-pressed={isSelected}
              className={cn(
                "flex h-6 w-6 items-center justify-center rounded-04 transition-colors focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-border-04",
                isSelected
                  ? "bg-background-neutral-00 text-text-05 shadow-sm"
                  : "text-text-03 hover:text-text-05"
              )}
              onClick={() => onChange(option.value)}
            >
              <Icon size={14} aria-hidden="true" />
            </button>
          </Tooltip>
        );
      })}
    </div>
  );
}
