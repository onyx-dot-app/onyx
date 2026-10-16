"use client";

import { useTranslations } from "next-intl";
import { Button } from "@opal/components";
import type { ActionPolicy } from "@/app/craft/v1/apps/registry";

interface PolicyToggleProps {
  value: ActionPolicy;
  disabled?: boolean;
  label?: string;
  onChange: (value: ActionPolicy) => void;
}

/** Three-state Craft approval policy selector, shared by per-action and
 * per-tool policy rows. */
export default function PolicyToggle({
  value,
  onChange,
  disabled = false,
  label,
}: PolicyToggleProps) {
  const t = useTranslations("actions");

  const policyOptions: { value: ActionPolicy; label: string }[] = [
    { value: "ALWAYS", label: t("policyToggle.always.label") },
    { value: "ASK", label: t("policyToggle.ask.label") },
    { value: "DENY", label: t("policyToggle.deny.label") },
  ];

  return (
    <div className="flex gap-1 shrink-0" role="group" aria-label={label}>
      {policyOptions.map((option) => (
        <Button
          key={option.value}
          disabled={disabled}
          aria-pressed={value === option.value}
          size="xs"
          disabled={disabled}
          aria-pressed={value === option.value}
          prominence={value === option.value ? "primary" : "tertiary"}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </Button>
      ))}
    </div>
  );
}
