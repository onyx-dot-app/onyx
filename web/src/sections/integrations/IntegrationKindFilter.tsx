"use client";

import { useTranslations } from "next-intl";
import { Button, Dropdown } from "@opal/components";
import { SvgFilter } from "@opal/icons";
import type { IntegrationKind } from "@/lib/integrations/types";

export type IntegrationKindFilterValue = "all" | IntegrationKind;

const VALUES: readonly IntegrationKindFilterValue[] = ["all", "mcp", "api"];

interface IntegrationKindFilterProps {
  value: IntegrationKindFilterValue;
  onChange: (value: IntegrationKindFilterValue) => void;
}

/** A filter button that shows all integrations, MCP servers only, or apps only. */
export default function IntegrationKindFilter({
  value,
  onChange,
}: IntegrationKindFilterProps) {
  const t = useTranslations("admin.integrations.filters");
  return (
    <Dropdown align="end" width={60}>
      <Dropdown.Trigger asChild>
        <Button
          prominence="tertiary"
          icon={SvgFilter}
          interaction={value === "all" ? "rest" : "hover"}
          aria-label={
            value === "all" ? t("label") : t("selected", { type: t(value) })
          }
          tooltip={t("label")}
        >
          {value === "all" ? undefined : t(value)}
        </Button>
      </Dropdown.Trigger>
      <Dropdown.Data
        label={t("label")}
        items={VALUES.map((option) => ({
          kind: "option" as const,
          value: option,
          title: t(option),
        }))}
        value={value}
        onSelect={(option) => {
          const next = VALUES.find((candidate) => candidate === option.value);
          if (next) onChange(next);
        }}
      />
    </Dropdown>
  );
}
