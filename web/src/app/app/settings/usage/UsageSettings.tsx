"use client";

import { IconLoader } from "@opal/loaders";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useMemo, useState } from "react";
import { IllustrationContent, Section } from "@opal/layouts";
import { SvgEmpty, SvgPlugBroken } from "@opal/illustrations";
import { Button, Collapsible, Divider, Text } from "@opal/components";
import { SvgChevronDown, SvgChevronRight, SvgChevronUp } from "@opal/icons";
import { cn } from "@opal/utils";
import {
  useUserUsage,
  type UsagePerDayByModel,
  type ModelPrice,
} from "@/app/app/settings/usage/lib";
import {
  InputDateRangePicker,
  rangeForInclusiveDays,
  type DateRange,
} from "@opal/components";
import { formatCalendarDay } from "@/lib/dateUtils";
import {
  formatCurrencyFromCents as formatDollars,
  formatTokenCount as formatTokens,
} from "@/lib/format";
import SettingsSection from "@/views/settings/SettingsSection";

interface ModelCostRowsProps {
  rows: UsagePerDayByModel[];
}

const COLLAPSED_USAGE_ROW_COUNT = 3;

/** One row per model with its cost and tokens; the priciest rows show first. */
function ModelCostRows({ rows }: ModelCostRowsProps) {
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
    <>
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
                  <Text as="p" font="main-ui-action" color="text-03">
                    {row.model}
                  </Text>
                </Section>
                <Text
                  as="p"
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
                as="p"
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
                  .filter((label): label is string => label !== false)
                  // One pair message per join so translators own the separator.
                  .reduce((first, rest) =>
                    t("modelUsage.joined", { first, rest })
                  )}
              </Text>
            </Section>
          </div>
        );
      })}
      {isExpandable && (
        <Section
          flexDirection="row"
          width="auto"
          height="fit"
          padding={0.25}
          data-testid="usage-models-expander"
          className={cn(
            "relative z-10 -mx-4 -mb-4 self-stretch",
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
        </Section>
      )}
    </>
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
  if (other === null) return false;
  // Two providers of one type can list the same model at different prices.
  if (
    price.model_configuration_id !== null &&
    other.model_configuration_id !== null
  ) {
    return price.model_configuration_id === other.model_configuration_id;
  }
  return price.model === other.model && price.provider === other.provider;
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
    <SettingsSection
      title={t("modelPrices.title")}
      description={t("modelPrices.description")}
    >
      {groups.length === 0 ? (
        <Text font="main-ui-body" color="text-03" as="p">
          {t("modelPrices.unavailable")}
        </Text>
      ) : (
        <Section gap={0.25} alignItems="stretch" justifyContent="start">
          {groups.map(({ provider, models }) => {
            const open = expanded.has(provider);
            return (
              <Collapsible.Root
                key={provider}
                open={open}
                onOpenChange={() => toggle(provider)}
              >
                <Collapsible.Trigger className="flex w-full flex-row items-center justify-between cursor-pointer select-none py-1.5">
                  <Text as="p" font="main-ui-action" color="text-03">
                    {provider}
                  </Text>
                  <SvgChevronRight
                    className={cn(
                      "w-4 h-4 text-text-03 transition-transform",
                      open && "rotate-90"
                    )}
                  />
                </Collapsible.Trigger>
                <Collapsible.Content>
                  <Section gap={0} alignItems="stretch" justifyContent="start">
                    {models.map((price) => (
                      <Section
                        key={`${provider}-${price.model_configuration_id ?? price.model}`}
                        flexDirection="row"
                        justifyContent="between"
                        width="auto"
                        height="fit"
                        gap={2}
                        className="my-1 ms-3"
                      >
                        <Text
                          as="p"
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
                          as="p"
                          font="secondary-body"
                          color="text-03"
                          wordWrap="whitespace-nowrap"
                        >
                          {t("modelPrices.priceRow", {
                            input: formatMtok(price.input_per_mtok),
                            output: formatMtok(price.output_per_mtok),
                            cache: formatMtok(
                              price.cache_per_mtok ?? price.input_per_mtok
                            ),
                          })}
                        </Text>
                      </Section>
                    ))}
                  </Section>
                </Collapsible.Content>
              </Collapsible.Root>
            );
          })}
        </Section>
      )}
    </SettingsSection>
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
  const locale = useLocale();
  // budget_* are null when the user has no cost limit; show a graceful empty state.
  const hasBudget = budgetCents !== null;
  const remaining = budgetRemainingCents ?? 0;
  const spent = hasBudget ? Math.max(0, budgetCents - remaining) : 0;
  const usedFraction =
    hasBudget && budgetCents > 0 ? Math.min(1, spent / budgetCents) : 0;
  const budgetReset = budgetResetAt
    ? t("budget.resetsOn", {
        date: formatCalendarDay(budgetResetAt.slice(0, 10), locale),
      })
    : null;

  return (
    <SettingsSection title={t("budget.title")}>
      {hasBudget ? (
        <Section gap={0.5} alignItems="start" justifyContent="start">
          <Text as="p" font="main-ui-body" color="text-03">
            {t("budget.remaining", { amount: formatDollars(remaining) })}
          </Text>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-background-neutral-03">
            <div
              className={cn(
                "h-full rounded-full",
                usedFraction >= 1 ? "bg-status-error-05" : "bg-theme-primary-05"
              )}
              style={{ width: `${usedFraction * 100}%` }}
            />
          </div>
          <Section
            flexDirection="row"
            justifyContent="between"
            height="fit"
            gap={4}
            wrap
            wrapGap={1}
          >
            {budgetReset && (
              <Text as="p" font="secondary-body" color="text-03">
                {budgetReset}
              </Text>
            )}
            <Text as="p" font="secondary-body" color="text-03">
              {t("budget.limit", { amount: formatDollars(budgetCents) })}
            </Text>
          </Section>
        </Section>
      ) : (
        <Text font="main-ui-body" color="text-03" as="p">
          {t("budget.none")}
        </Text>
      )}
    </SettingsSection>
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

  const loaded = !isLoading && !error && data;

  return (
    <Section gap={8}>
      <SettingsSection
        title={t("usageThisPeriod.title")}
        description={
          loaded
            ? t("usageThisPeriod.description", {
                amount: formatDollars(loaded.window_cost_cents),
              })
            : undefined
        }
        rightChildren={
          <InputDateRangePicker
            value={dateRange}
            onValueChange={setDateRange}
            size="sm"
          />
        }
      >
        {isLoading ? (
          <Section
            flexDirection="row"
            justifyContent="center"
            alignItems="center"
            width="full"
          >
            <IconLoader />
          </Section>
        ) : !loaded ? (
          <Section height="fit">
            <IllustrationContent
              size="sm"
              illustration={SvgPlugBroken}
              title={t("loadError.title")}
              description={t("loadError.description")}
            />
          </Section>
        ) : loaded.per_day_by_model.length === 0 ? (
          <Section height="fit">
            <IllustrationContent
              size="sm"
              illustration={SvgEmpty}
              title={t("empty.title")}
              description={t("empty.description")}
            />
          </Section>
        ) : (
          <ModelCostRows rows={loaded.per_day_by_model} />
        )}
      </SettingsSection>
      {loaded && (
        <>
          <BudgetSection
            budgetCents={loaded.budget_cents}
            budgetRemainingCents={loaded.budget_remaining_cents}
            budgetResetAt={loaded.budget_reset_at}
          />
          <ModelPriceSection
            prices={loaded.available_model_prices ?? []}
            defaultPrice={loaded.selected_model_price}
          />
        </>
      )}
    </Section>
  );
}
