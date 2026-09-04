"use client";

import { useTranslations } from "next-intl";
import { useEffect, useMemo, useState } from "react";
import { Section } from "@/layouts/general-layouts";
import { Content } from "@opal/layouts";
import { Button, Text, EmptyMessageCard, Divider } from "@opal/components";
import {
  SvgBarChart,
  SvgWallet,
  SvgCreditCard,
  SvgSimpleLoader,
  SvgChevronDown,
  SvgChevronRight,
  SvgChevronUp,
} from "@opal/icons";
import Card from "@/refresh-components/cards/Card";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/refresh-components/Collapsible";
import { cn } from "@opal/utils";
import {
  useUserUsage,
  type UsagePerDayByModel,
  type ModelPrice,
} from "@/app/app/settings/usage/lib";
import {
  DateRangePicker,
  rangeForInclusiveDays,
  type DateRange,
} from "@/refresh-components/DateRangePicker";
import { formatCalendarDay } from "@/lib/dateUtils";
import {
  formatCurrencyFromCents as formatDollars,
  formatTokenCount as formatTokens,
} from "@/lib/format";

interface WindowCostSectionProps {
  windowCostCents: number;
  rows: UsagePerDayByModel[];
}

const COLLAPSED_USAGE_ROW_COUNT = 3;

function WindowCostSection({ windowCostCents, rows }: WindowCostSectionProps) {
  const t = useTranslations("settings.usage");
  const [showAll, setShowAll] = useState(false);
  const hasCache = rows.some((row) => row.cache_read_tokens > 0);
  const hasCacheWrites = rows.some((row) => row.cache_creation_tokens > 0);
  const modelRows = useMemo(() => {
    const byModel = new Map<string, Omit<UsagePerDayByModel, "day">>();
    for (const row of rows) {
      const model = byModel.get(row.model) ?? {
        model: row.model,
        input_tokens: 0,
        output_tokens: 0,
        cache_read_tokens: 0,
        cache_creation_tokens: 0,
        cost_cents: 0,
      };
      model.input_tokens += row.input_tokens;
      model.output_tokens += row.output_tokens;
      model.cache_read_tokens += row.cache_read_tokens;
      model.cache_creation_tokens += row.cache_creation_tokens;
      model.cost_cents += row.cost_cents;
      byModel.set(row.model, model);
    }
    return Array.from(byModel.values()).sort(
      (a, b) => b.cost_cents - a.cost_cents
    );
  }, [rows]);
  const maxModelCost = modelRows[0]?.cost_cents ?? 0;
  const isExpandable = modelRows.length > COLLAPSED_USAGE_ROW_COUNT;
  const displayedRows = showAll
    ? modelRows
    : modelRows.slice(0, COLLAPSED_USAGE_ROW_COUNT + 1);
  const hiddenRowCount = modelRows.length - COLLAPSED_USAGE_ROW_COUNT;

  return (
    <Section gap={0.75} justifyContent="start">
      <Content
        icon={SvgBarChart}
        title={t("usageThisPeriod.title")}
        description={t("usageThisPeriod.description", {
          amount: formatDollars(windowCostCents),
        })}
        sizePreset="main-content"
        variant="section"
        width="full"
      />

      {rows.length === 0 ? (
        <EmptyMessageCard
          sizePreset="main-ui"
          title={t("empty.title")}
          description={t("empty.description")}
        />
      ) : (
        <Card>
          {displayedRows.map((row, index) => {
            const isPreview = !showAll && index === COLLAPSED_USAGE_ROW_COUNT;

            return (
              <div
                key={row.model}
                data-testid={isPreview ? "usage-model-preview" : undefined}
                aria-hidden={isPreview || undefined}
                className={cn(
                  isPreview &&
                    "max-h-10 overflow-hidden [mask-image:linear-gradient(to_bottom,black_5%,transparent_75%)]"
                )}
              >
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
                    </Section>
                    <Text
                      font="main-ui-action"
                      color="text-03"
                      wordWrap="whitespace-nowrap"
                    >
                      {formatDollars(row.cost_cents)}
                    </Text>
                  </Section>

                  {/* Cost bar — proportional to the priciest row in the window. */}
                  <div className="w-full h-1.5 rounded-full bg-background-neutral-03 overflow-hidden">
                    <div
                      className="h-full rounded-full bg-theme-primary-05"
                      style={{
                        width:
                          maxModelCost > 0
                            ? `${Math.max(2, (row.cost_cents / maxModelCost) * 100)}%`
                            : "0%",
                      }}
                    />
                  </div>

                  <Text
                    font="secondary-body"
                    color="text-03"
                    data-testid="usage-model-tokens"
                  >
                    {[
                      t("modelUsage.tokensIn.label", {
                        count: formatTokens(row.input_tokens),
                      }),
                      t("modelUsage.tokensOut.label", {
                        count: formatTokens(row.output_tokens),
                      }),
                      hasCache &&
                        t("modelUsage.cacheReads.label", {
                          count: formatTokens(row.cache_read_tokens),
                        }),
                      hasCacheWrites &&
                        t("modelUsage.cacheWrites.label", {
                          count: formatTokens(row.cache_creation_tokens),
                        }),
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </Text>
                </Section>
              </div>
            );
          })}
          {isExpandable && (
            <div
              data-testid="usage-models-expander"
              className={cn(
                "relative z-10 -mx-4 -mb-4 flex self-stretch justify-center pb-1 pt-1",
                showAll ? "mt-1" : "-mt-8"
              )}
            >
              <Button
                prominence="tertiary"
                size="2xs"
                rightIcon={showAll ? SvgChevronUp : SvgChevronDown}
                aria-expanded={showAll}
                aria-label={
                  showAll
                    ? t("showFewerModels.ariaLabel")
                    : t("showMoreModels.ariaLabel", { count: hiddenRowCount })
                }
                onClick={() => setShowAll((value) => !value)}
              >
                {showAll
                  ? t("showLess.label")
                  : t("showMore.label", { count: hiddenRowCount })}
              </Button>
            </div>
          )}
        </Card>
      )}
    </Section>
  );
}

interface ModelPriceSectionProps {
  prices: ModelPrice[];
  defaultPrice: ModelPrice | null;
}

function formatMtok(value: number | null): string {
  return value !== null ? `$${value.toFixed(2)}` : "—";
}

function isSameModelPrice(
  price: ModelPrice,
  other: ModelPrice | null
): boolean {
  return (
    other !== null &&
    price.model === other.model &&
    price.provider === other.provider
  );
}

// Every available model's price (USD/1M, input · output · cache), grouped into a
// collapsible menu per provider — click a provider to expand its models. Mirrors
// the chat model selector so users can compare costs, not just the default.
function ModelPriceSection({ prices, defaultPrice }: ModelPriceSectionProps) {
  const t = useTranslations("settings.usage");
  const groups = useMemo(() => {
    // t is stable per locale, listed below to satisfy the deps lint.
    const byProvider = new Map<string, ModelPrice[]>();
    for (const price of prices) {
      const key = price.provider ?? t("modelPrices.otherProvider.label");
      const list = byProvider.get(key) ?? [];
      list.push(price);
      byProvider.set(key, list);
    }
    return Array.from(byProvider.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([provider, models]) => ({ provider, models }));
  }, [prices, t]);

  // Expand the provider that holds the default model (else the first).
  const defaultProvider = useMemo(
    () =>
      prices.find((price) => isSameModelPrice(price, defaultPrice))?.provider ??
      groups[0]?.provider ??
      null,
    [prices, defaultPrice, groups]
  );
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  useEffect(() => {
    if (defaultProvider) setExpanded(new Set([defaultProvider]));
  }, [defaultProvider]);

  function toggle(provider: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(provider)) next.delete(provider);
      else next.add(provider);
      return next;
    });
  }

  return (
    <Section gap={0.75} justifyContent="start">
      <Content
        icon={SvgCreditCard}
        title={t("modelPrices.title")}
        description={t("modelPrices.description")}
        sizePreset="main-content"
        variant="section"
        width="full"
      />
      <Card>
        {groups.length === 0 ? (
          <Text font="main-ui-body" color="text-01">
            {t("modelPrices.unavailable")}
          </Text>
        ) : (
          <Section gap={0.25} alignItems="stretch" justifyContent="start">
            {groups.map(({ provider, models }) => {
              const open = expanded.has(provider);
              return (
                <Collapsible
                  key={provider}
                  open={open}
                  onOpenChange={() => toggle(provider)}
                  className="flex flex-col"
                >
                  <CollapsibleTrigger className="flex flex-row items-center justify-between cursor-pointer select-none py-1.5">
                    <Text font="main-ui-action" color="text-03">
                      {provider}
                    </Text>
                    <SvgChevronRight
                      className={cn(
                        "w-4 h-4 text-text-03 transition-transform",
                        open && "rotate-90"
                      )}
                    />
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                    <Section
                      gap={0}
                      alignItems="stretch"
                      justifyContent="start"
                    >
                      {models.map((price) => (
                        <div
                          key={`${provider}-${price.model}`}
                          className="flex flex-row items-center justify-between gap-2 py-1 ps-3"
                        >
                          <Text
                            font="secondary-body"
                            color="text-05"
                            wordWrap="whitespace-nowrap"
                          >
                            {isSameModelPrice(price, defaultPrice)
                              ? t("modelPrices.defaultTag.label", {
                                  model: price.model,
                                })
                              : price.model}
                          </Text>
                          <Text
                            font="secondary-body"
                            color="text-03"
                            wordWrap="whitespace-nowrap"
                          >
                            {`${formatMtok(price.input_per_mtok)} in · ${formatMtok(
                              price.output_per_mtok
                            )} out · ${formatMtok(
                              price.cache_per_mtok ?? price.input_per_mtok
                            )} cache`}
                          </Text>
                        </div>
                      ))}
                    </Section>
                  </CollapsibleContent>
                </Collapsible>
              );
            })}
          </Section>
        )}
      </Card>
    </Section>
  );
}

interface BudgetSectionProps {
  budgetCents: number | null;
  budgetRemainingCents: number | null;
  budgetResetAt: string | null;
}

function BudgetSection({
  budgetCents,
  budgetRemainingCents,
  budgetResetAt,
}: BudgetSectionProps) {
  const t = useTranslations("settings.usage");
  // budget_* are null when the user has no cost limit; show a graceful empty state.
  const hasBudget = budgetCents !== null;
  const remaining = budgetRemainingCents ?? 0;
  const spent = hasBudget ? Math.max(0, budgetCents - remaining) : 0;
  const usedFraction =
    hasBudget && budgetCents > 0 ? Math.min(1, spent / budgetCents) : 0;
  const budgetReset = budgetResetAt
    ? t("budget.resetsOn", {
        date: formatCalendarDay(budgetResetAt.slice(0, 10)),
      })
    : null;

  return (
    <Section gap={0.75} justifyContent="start">
      <Content
        icon={SvgWallet}
        title={t("budget.title")}
        sizePreset="main-content"
        variant="section"
        width="full"
      />
      <Card>
        {hasBudget ? (
          <Section gap={0.5} alignItems="start" justifyContent="start">
            <div className="flex w-full flex-wrap items-baseline gap-x-4 gap-y-1">
              <Text font="main-ui-body" color="text-03">
                {t("budget.remaining", { amount: formatDollars(remaining) })}
              </Text>
            </div>
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-background-neutral-03">
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
            <div className="flex w-full flex-wrap justify-between gap-x-4 gap-y-1">
              {budgetReset && (
                <Text font="secondary-body" color="text-03">
                  {budgetReset}
                </Text>
              )}
              <Text font="secondary-body" color="text-03">
                {t("budget.limit", { amount: formatDollars(budgetCents) })}
              </Text>
            </div>
          </Section>
        ) : (
          <Text font="main-ui-body" color="text-01">
            {t("budget.none")}
          </Text>
        )}
      </Card>
    </Section>
  );
}

export default function UsageSettings() {
  const t = useTranslations("settings.usage");
  const [dateRange, setDateRange] = useState<DateRange>(
    rangeForInclusiveDays(30)
  );
  const { data, error, isLoading } = useUserUsage(dateRange);

  useEffect(() => {
    if (error) console.error("Failed to load usage", error);
  }, [error]);

  return (
    <Section gap={2}>
      <Section gap={0.75} justifyContent="start">
        <div className="flex w-full flex-wrap items-center justify-between gap-3">
          <Text font="heading-h3">{t("header.title")}</Text>
          <DateRangePicker
            value={dateRange}
            onValueChange={setDateRange}
            size="sm"
          />
        </div>

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
            title={t("loadError.title")}
            description={t("loadError.description")}
          />
        ) : (
          <Section gap={2}>
            <WindowCostSection
              windowCostCents={data.window_cost_cents}
              rows={data.per_day_by_model}
            />
            <BudgetSection
              budgetCents={data.budget_cents}
              budgetRemainingCents={data.budget_remaining_cents}
              budgetResetAt={data.budget_reset_at}
            />
            <ModelPriceSection
              prices={data.available_model_prices ?? []}
              defaultPrice={data.selected_model_price}
            />
          </Section>
        )}
      </Section>
    </Section>
  );
}
