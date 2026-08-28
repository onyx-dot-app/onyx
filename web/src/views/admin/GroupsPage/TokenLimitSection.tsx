"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { SvgPlusCircle, SvgMinusCircle } from "@opal/icons";
import { Button, Card } from "@opal/components";
import { Disabled } from "@opal/core";
import type { RichStr } from "@opal/types";
import { planTagProps } from "@/lib/tier-badge";
import { Section } from "@/layouts/general-layouts";
import InputNumber from "@/refresh-components/inputs/InputNumber";
import Text from "@/refresh-components/texts/Text";
import SimpleCollapsible from "@/refresh-components/SimpleCollapsible";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface TokenLimit {
  tokenId: number | null;
  enabled: boolean;
  tokenBudget: number | null;
  periodDays: number | null;
  costBudgetDollars: number | null;
}

type TokenLimitValueField = "tokenBudget" | "periodDays" | "costBudgetDollars";

interface TokenLimitSectionProps {
  limits: TokenLimit[];
  onLimitsChange: (limits: TokenLimit[]) => void;
  disabled?: boolean;
  disabledTooltip?: string | RichStr;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

function TokenLimitSection({
  limits,
  onLimitsChange,
  disabled,
  disabledTooltip,
}: TokenLimitSectionProps) {
  const t = useTranslations("admin.groups");
  const [rowKeys, setRowKeys] = useState<{
    keys: number[];
    nextKey: number;
  }>({
    keys: limits.map((_, i) => i),
    nextKey: limits.length,
  });

  // Sync keys if the parent provides a different number of limits externally
  // (e.g. loaded from server after initial mount).
  if (rowKeys.keys.length < limits.length) {
    const keysToAdd = limits.length - rowKeys.keys.length;
    setRowKeys({
      keys: [
        ...rowKeys.keys,
        ...Array.from(
          { length: keysToAdd },
          (_, index) => rowKeys.nextKey + index
        ),
      ],
      nextKey: rowKeys.nextKey + keysToAdd,
    });
  } else if (rowKeys.keys.length > limits.length) {
    setRowKeys({
      keys: rowKeys.keys.slice(0, limits.length),
      nextKey: rowKeys.nextKey,
    });
  }

  function addLimit() {
    const emptyIndex = limits.findIndex(
      (l) =>
        l.tokenBudget === null &&
        l.periodDays === null &&
        l.costBudgetDollars === null
    );
    if (emptyIndex !== -1) return;
    setRowKeys((prev) => ({
      keys: [...prev.keys, prev.nextKey],
      nextKey: prev.nextKey + 1,
    }));
    onLimitsChange([
      ...limits,
      {
        tokenId: null,
        enabled: true,
        tokenBudget: null,
        periodDays: null,
        costBudgetDollars: null,
      },
    ]);
  }

  function removeLimit(index: number) {
    setRowKeys((prev) => ({
      keys: prev.keys.filter((_, i) => i !== index),
      nextKey: prev.nextKey,
    }));
    onLimitsChange(limits.filter((_, i) => i !== index));
  }

  function updateLimit(
    index: number,
    field: TokenLimitValueField,
    value: number | null
  ) {
    onLimitsChange(
      limits.map((l, i) => (i === index ? { ...l, [field]: value } : l))
    );
  }

  return (
    <SimpleCollapsible>
      <SimpleCollapsible.Header
        title={t("tokenLimits.section.title")}
        description={t("tokenLimits.section.description")}
        tag={
          disabled ? { ...planTagProps("enterprise"), size: "sm" } : undefined
        }
      />
      <SimpleCollapsible.Content>
        <Disabled disabled={disabled} tooltip={disabledTooltip}>
          <Card border="solid" rounding={4}>
            <Section alignItems="start" height="fit">
              <Section
                gap={2}
                height="auto"
                alignItems="stretch"
                justifyContent="start"
                width="full"
              >
                {/* Column headers */}
                <div className="flex flex-wrap items-center gap-1 pr-[40px]">
                  <div className="flex-1 flex items-center min-w-[160px]">
                    <Text mainUiAction text04>
                      {t("tokenLimits.tokenLimit.header")}
                    </Text>
                    <Text mainUiMuted text03 className="ml-0.5">
                      {t("tokenLimits.tokenLimit.unit")}
                    </Text>
                  </div>
                  <div className="flex-1 flex items-center min-w-[160px]">
                    <Text mainUiAction text04>
                      {t("tokenLimits.costLimit.header")}
                    </Text>
                    <Text mainUiMuted text03 className="ml-0.5">
                      {t("tokenLimits.costLimit.unit")}
                    </Text>
                  </div>
                  <div className="flex-1 flex items-center min-w-[160px]">
                    <Text mainUiAction text04>
                      {t("tokenLimits.timeWindow.header")}
                    </Text>
                    <Text mainUiMuted text03 className="ml-0.5">
                      {t("tokenLimits.timeWindow.unit")}
                    </Text>
                  </div>
                </div>

                {/* Limit rows */}
                {limits.map((limit, i) => (
                  <div
                    key={rowKeys.keys[i]}
                    className="flex items-center gap-1"
                  >
                    <div className="flex-1">
                      <InputNumber
                        value={limit.tokenBudget}
                        onChange={(v) => updateLimit(i, "tokenBudget", v)}
                        min={1}
                        placeholder={t("tokenLimits.tokenLimit.placeholder")}
                      />
                    </div>
                    <div className="flex-1">
                      <InputNumber
                        value={limit.costBudgetDollars}
                        onChange={(v) => updateLimit(i, "costBudgetDollars", v)}
                        min={0.01}
                        step={0.01}
                        decimalPlaces={2}
                        placeholder={t("tokenLimits.costLimit.placeholder")}
                      />
                    </div>
                    <div className="flex-1">
                      <InputNumber
                        value={limit.periodDays}
                        onChange={(v) => updateLimit(i, "periodDays", v)}
                        min={1}
                        placeholder="1"
                      />
                    </div>
                    <Button
                      size="xs"
                      prominence="internal"
                      icon={SvgMinusCircle}
                      onClick={() => removeLimit(i)}
                    />
                  </div>
                ))}

                {/* Add button */}
                <Button
                  icon={SvgPlusCircle}
                  prominence="secondary"
                  size="md"
                  onClick={addLimit}
                >
                  {t("tokenLimits.addLimit.label")}
                </Button>
              </Section>
            </Section>
          </Card>
        </Disabled>
      </SimpleCollapsible.Content>
    </SimpleCollapsible>
  );
}

export default TokenLimitSection;
