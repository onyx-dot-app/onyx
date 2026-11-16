"use client";

import { useTranslations } from "next-intl";
import { Button } from "@opal/components";
import { Section } from "@opal/layouts";
import type { ActionPolicy } from "@/app/craft/v1/apps/registry";

interface PolicyToggleProps {
  /** `null` presses no button, for a value that is not set. */
  value: ActionPolicy | null;
  disabled?: boolean;
  label?: string;
  onChange: (value: ActionPolicy) => void;
}

/** Three-state approval policy selector (Allow, Ask, Blocked), shared by
 * per-action and per-tool policy rows. */
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
    <Section
      flexDirection="row"
      width="auto"
      height="auto"
      gap={1}
      className="shrink-0"
      role="group"
      aria-label={label}
    >
      {policyOptions.map((option) => (
        <Button
          key={option.value}
          disabled={disabled}
          aria-pressed={value === option.value}
          size="xs"
          prominence={value === option.value ? "primary" : "tertiary"}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </Button>
      ))}
    </Section>
  );
}
