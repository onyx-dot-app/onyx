"use client";

import { Button } from "@opal/components";
import type { EndpointPolicy } from "@/app/craft/v1/apps/registry";

const POLICY_OPTIONS: { value: EndpointPolicy; label: string }[] = [
  { value: "ALWAYS", label: "Auto-approve" },
  { value: "ASK", label: "Ask" },
  { value: "DENY", label: "Deny" },
];

interface PolicyToggleProps {
  value: EndpointPolicy;
  onChange: (value: EndpointPolicy) => void;
}

/** Three-state Craft approval policy selector, shared by per-action and
 * per-tool policy rows. */
export default function PolicyToggle({ value, onChange }: PolicyToggleProps) {
  return (
    <div className="flex gap-1 shrink-0">
      {POLICY_OPTIONS.map((option) => (
        <Button
          key={option.value}
          size="xs"
          prominence={value === option.value ? "primary" : "tertiary"}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </Button>
      ))}
    </div>
  );
}
