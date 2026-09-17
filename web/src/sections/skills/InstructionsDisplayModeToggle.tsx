"use client";

import { useTranslations } from "next-intl";
import { Tooltip } from "@opal/components";
import { SvgCode, SvgEye } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import { cn } from "@opal/utils";

export type InstructionsDisplayMode = "rendered" | "raw";

// Modules cannot call hooks, so the options hold message keys (inside the
// `skills.sections` namespace) and the component resolves them with `t`.
type DisplayModeOption = {
  value: InstructionsDisplayMode;
  labelKey: string;
  icon: IconFunctionComponent;
};

const OPTIONS = [
  {
    value: "rendered",
    labelKey: "instructionsToggle.rendered.label",
    icon: SvgEye,
  },
  { value: "raw", labelKey: "instructionsToggle.raw.label", icon: SvgCode },
] as const satisfies readonly DisplayModeOption[];

interface InstructionsDisplayModeToggleProps {
  value: InstructionsDisplayMode;
  onChange: (value: InstructionsDisplayMode) => void;
}

export default function InstructionsDisplayModeToggle({
  value,
  onChange,
}: InstructionsDisplayModeToggleProps) {
  const t = useTranslations("skills.sections");

  return (
    <div
      role="group"
      className="inline-flex shrink-0 rounded-08 border border-border-01 bg-background-tint-01 p-0.5"
      aria-label={t("instructionsToggle.group.ariaLabel")}
    >
      {OPTIONS.map((option) => {
        const isSelected = option.value === value;
        const Icon = option.icon;
        const label = t(option.labelKey);
        return (
          <Tooltip key={option.value} tooltip={label} side="top">
            <button
              type="button"
              aria-label={label}
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
