"use client";

import { SvgPlusCircle, SvgMinusCircle } from "@opal/icons";
import { Button } from "@opal/components";
import { Section } from "@/layouts/general-layouts";
import Card from "@/refresh-components/cards/Card";
import InputNumber from "@/refresh-components/inputs/InputNumber";
import Text from "@/refresh-components/texts/Text";
import IconButton from "@/refresh-components/buttons/IconButton";
import SimpleCollapsible from "@/refresh-components/SimpleCollapsible";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface TokenLimit {
  tokenBudget: number | null;
  periodHours: number | null;
}

interface TokenLimitSectionProps {
  limits: TokenLimit[];
  onLimitsChange: (limits: TokenLimit[]) => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

function TokenLimitSection({ limits, onLimitsChange }: TokenLimitSectionProps) {
  function addLimit() {
    const emptyIndex = limits.findIndex(
      (l) => l.tokenBudget === null && l.periodHours === null
    );
    if (emptyIndex !== -1) return;
    onLimitsChange([...limits, { tokenBudget: null, periodHours: null }]);
  }

  function removeLimit(index: number) {
    onLimitsChange(limits.filter((_, i) => i !== index));
  }

  function updateLimit(
    index: number,
    field: keyof TokenLimit,
    value: number | null
  ) {
    onLimitsChange(
      limits.map((l, i) => (i === index ? { ...l, [field]: value } : l))
    );
  }

  return (
    <SimpleCollapsible>
      <SimpleCollapsible.Header
        title="Token Rate Limit"
        description="Limit number of tokens this group can use within a given time period."
      />
      <SimpleCollapsible.Content>
        <Card>
          <Section
            gap={0.5}
            height="auto"
            alignItems="stretch"
            justifyContent="start"
            width="full"
          >
            {/* Column headers */}
            <div className="flex flex-wrap items-center gap-1 pr-[40px]">
              <div className="flex-1 flex items-center min-w-[160px]">
                <Text mainUiAction text04>
                  Token Limit
                </Text>
                <Text mainUiMuted text03 className="ml-0.5">
                  (thousand tokens)
                </Text>
              </div>
              <div className="flex-1 flex items-center min-w-[160px]">
                <Text mainUiAction text04>
                  Time Window
                </Text>
                <Text mainUiMuted text03 className="ml-0.5">
                  (hours)
                </Text>
              </div>
            </div>

            {/* Limit rows */}
            {limits.map((limit, i) => (
              <div key={i} className="flex items-center gap-1">
                <div className="flex-1">
                  <InputNumber
                    value={limit.tokenBudget}
                    onChange={(v) => updateLimit(i, "tokenBudget", v)}
                    min={0}
                    placeholder="Token limit in thousands"
                  />
                </div>
                <div className="flex-1">
                  <InputNumber
                    value={limit.periodHours}
                    onChange={(v) => updateLimit(i, "periodHours", v)}
                    min={0}
                    placeholder="24"
                  />
                </div>
                <IconButton
                  small
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
              Add Limit
            </Button>
          </Section>
        </Card>
      </SimpleCollapsible.Content>
    </SimpleCollapsible>
  );
}

export default TokenLimitSection;
