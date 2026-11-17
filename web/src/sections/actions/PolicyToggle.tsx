"use client";

import { useTranslations } from "next-intl";
import { Button } from "@opal/components";
import { Section } from "@opal/layouts";
import type { PolicyValue } from "@/lib/integrations/types";

interface PolicyToggleProps {
  /** `null` presses no button, for a value that is not set. */
  value: PolicyValue | null;
  disabled?: boolean;
  label?: string;
  onChange: (value: PolicyValue) => void;
}

export default function PolicyToggle({
  value,
  onChange,
  disabled = false,
  label,
}: PolicyToggleProps) {
  const t = useTranslations("actions");

  const policyOptions: { value: PolicyValue; label: string }[] = [
    { value: "allow", label: t("policyToggle.always.label") },
    { value: "ask", label: t("policyToggle.ask.label") },
    { value: "blocked", label: t("policyToggle.deny.label") },
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
