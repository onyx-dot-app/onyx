"use client";

import { useState } from "react";
import { Section } from "@/layouts/general-layouts";
import { Content } from "@opal/layouts";
import { Text, EmptyMessageCard, Divider } from "@opal/components";
import {
  SvgBarChart,
  SvgWallet,
  SvgCreditCard,
  SvgSimpleLoader,
} from "@opal/icons";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import Card from "@/refresh-components/cards/Card";
import { cn } from "@opal/utils";
import {
  useUserUsage,
  type UsagePerDayByModel,
  type SelectedModelPrice,
} from "@/app/app/settings/usage/lib";

const DAYS_OPTIONS = ["7", "30"] as const;
const DEFAULT_DAYS = 30;

function formatDollars(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`;
}

function formatTokens(tokens: number): string {
  return tokens.toLocaleString();
}

interface WindowCostSectionProps {
  windowCostCents: number;
  rows: UsagePerDayByModel[];
}

function WindowCostSection({ windowCostCents, rows }: WindowCostSectionProps) {
  // Drives the relative bar widths in the breakdown.
  const maxRowCost = rows.reduce(
    (max, row) => Math.max(max, row.cost_cents),
    0
  );
  const hasCache = rows.some((row) => row.cache_read_tokens > 0);

  return (
    <Section gap={0.75} justifyContent="start">
      <Content
        icon={SvgBarChart}
        title="Usage this period"
        description={`${formatDollars(windowCostCents)} spent`}
        sizePreset="main-content"
        variant="section"
        width="full"
      />

      {rows.length === 0 ? (
        <EmptyMessageCard
          sizePreset="main-ui"
          title="No usage recorded yet"
          description="Your model usage and costs will show up here once you start chatting."
        />
      ) : (
        <Card>
          {rows.map((row, index) => (
            <div key={`${row.day}-${row.model}`}>
              {index > 0 && <Divider />}
              <Section gap={0.5} alignItems="start" justifyContent="start">
                <Section
                  flexDirection="row"
                  justifyContent="between"
                  alignItems="center"
                  width="full"
                  gap={1}
                >
                  <Section gap={0} alignItems="start" justifyContent="start">
                    <Text font="main-ui-action" color="text-03">
                      {row.model}
                    </Text>
                    <Text font="secondary-body" color="text-01">
                      {row.day}
                    </Text>
                  </Section>
                  <Text font="main-ui-action" color="text-03" nowrap>
                    {formatDollars(row.cost_cents)}
                  </Text>
                </Section>

                {/* Cost bar — proportional to the priciest row in the window. */}
                <div className="w-full h-1.5 rounded-full bg-background-neutral-03 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-theme-primary-05"
                    style={{
                      width:
                        maxRowCost > 0
                          ? `${Math.max(2, (row.cost_cents / maxRowCost) * 100)}%`
                          : "0%",
                    }}
                  />
                </div>

                <Text font="secondary-body" color="text-01">
                  {`${formatTokens(row.input_tokens)} in · ${formatTokens(
                    row.output_tokens
                  )} out${
                    hasCache
                      ? ` · ${formatTokens(row.cache_read_tokens)} cache`
                      : ""
                  }`}
                </Text>
              </Section>
            </div>
          ))}
        </Card>
      )}
    </Section>
  );
}

interface ModelPriceSectionProps {
  price: SelectedModelPrice | null;
}

function ModelPriceSection({ price }: ModelPriceSectionProps) {
  return (
    <Section gap={0.75} justifyContent="start">
      <Content
        icon={SvgCreditCard}
        title="Your model's price"
        sizePreset="main-content"
        variant="section"
        width="full"
      />
      <Card>
        {price &&
        price.input_per_mtok !== null &&
        price.output_per_mtok !== null ? (
          <Section
            flexDirection="row"
            justifyContent="between"
            alignItems="center"
            width="full"
            gap={1}
          >
            <Text font="main-ui-body" color="text-03">
              {`$${price.input_per_mtok.toFixed(2)} / 1M input`}
            </Text>
            <Text font="main-ui-body" color="text-03">
              {`$${price.output_per_mtok.toFixed(2)} / 1M output`}
            </Text>
          </Section>
        ) : (
          <Text font="main-ui-body" color="text-01">
            Price unavailable
          </Text>
        )}
      </Card>
    </Section>
  );
}

interface BudgetSectionProps {
  budgetCents: number | null;
  budgetRemainingCents: number | null;
  budgetPeriodHours: number | null;
}

// Hours -> a friendly window label so the budget reads "per week", not "per 168h".
function formatPeriod(hours: number | null): string {
  if (hours == null) return "";
  if (hours % 168 === 0) {
    const w = hours / 168;
    return w === 1 ? "week" : `${w} weeks`;
  }
  if (hours % 24 === 0) {
    const d = hours / 24;
    return d === 1 ? "day" : `${d} days`;
  }
  return hours === 1 ? "hour" : `${hours} hours`;
}

function BudgetSection({
  budgetCents,
  budgetRemainingCents,
  budgetPeriodHours,
}: BudgetSectionProps) {
  // budget_* are null until P5 enforcement ships; show a graceful empty state.
  const hasBudget = budgetCents !== null;
  const remaining = budgetRemainingCents ?? 0;
  const spent = hasBudget ? Math.max(0, budgetCents - remaining) : 0;
  const usedFraction =
    hasBudget && budgetCents > 0 ? Math.min(1, spent / budgetCents) : 0;

  return (
    <Section gap={0.75} justifyContent="start">
      <Content
        icon={SvgWallet}
        title="Budget"
        sizePreset="main-content"
        variant="section"
        width="full"
      />
      <Card>
        {hasBudget ? (
          <Section gap={0.5} alignItems="start" justifyContent="start">
            <Section
              flexDirection="row"
              justifyContent="between"
              alignItems="center"
              width="full"
              gap={1}
            >
              <Text font="main-ui-body" color="text-03">
                {`${formatDollars(remaining)} remaining`}
              </Text>
              <Text font="secondary-body" color="text-01">
                {`of ${formatDollars(budgetCents)}${
                  budgetPeriodHours ? ` per ${formatPeriod(budgetPeriodHours)}` : ""
                }`}
              </Text>
            </Section>
            <div className="w-full h-1.5 rounded-full bg-background-neutral-03 overflow-hidden">
              <div
                className={cn(
                  "h-full rounded-full",
                  usedFraction >= 1
                    ? "bg-status-error-05"
                    : "bg-theme-primary-05"
                )}
                style={{ width: `${usedFraction * 100}%` }}
              />
            </div>
          </Section>
        ) : (
          <Text font="main-ui-body" color="text-01">
            No budget set
          </Text>
        )}
      </Card>
    </Section>
  );
}

export default function UsageSettings() {
  const [days, setDays] = useState<string>(String(DEFAULT_DAYS));
  const { data, error, isLoading } = useUserUsage(Number(days));

  return (
    <Section gap={2}>
      <Section gap={0.75} justifyContent="start">
        <Section
          flexDirection="row"
          justifyContent="between"
          alignItems="center"
          width="full"
          gap={1}
        >
          <Content title="Usage" sizePreset="main-content" variant="section" />
          <div className="min-w-32">
            <InputSelect value={days} onValueChange={setDays}>
              <InputSelect.Trigger placeholder="Period" />
              <InputSelect.Content>
                {DAYS_OPTIONS.map((option) => (
                  <InputSelect.Item key={option} value={option}>
                    {`Last ${option} days`}
                  </InputSelect.Item>
                ))}
              </InputSelect.Content>
            </InputSelect>
          </div>
        </Section>

        {isLoading ? (
          <Card>
            <Section
              flexDirection="row"
              justifyContent="center"
              alignItems="center"
              width="full"
            >
              <SvgSimpleLoader />
            </Section>
          </Card>
        ) : error || !data ? (
          <EmptyMessageCard
            sizePreset="main-ui"
            title="Couldn't load usage"
            description="Something went wrong fetching your usage. Try again in a moment."
          />
        ) : (
          <Section gap={2}>
            <WindowCostSection
              windowCostCents={data.window_cost_cents}
              rows={data.per_day_by_model}
            />
            <ModelPriceSection price={data.selected_model_price} />
            <BudgetSection
              budgetCents={data.budget_cents}
              budgetRemainingCents={data.budget_remaining_cents}
              budgetPeriodHours={data.budget_period_hours}
            />
          </Section>
        )}
      </Section>
    </Section>
  );
}
