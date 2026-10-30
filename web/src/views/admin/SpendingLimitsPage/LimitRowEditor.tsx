"use client";

import { useFormatter, useLocale, useTranslations } from "next-intl";
import {
  Button,
  Card,
  InputCurrency,
  InputNumber,
  InputSingleSelect,
  ProgressBar,
  Text,
  type SelectOption,
} from "@opal/components";
import { InputVertical, Section } from "@opal/layouts";
import { SvgMinusCircle } from "@opal/icons";
import { formatCurrencyFromCents, formatTokenCount } from "@/lib/format";
import { PERIODS } from "@/lib/spendingLimits/types";
import type {
  DraftLimit,
  DraftLimitError,
} from "@/views/admin/SpendingLimitsPage/draft";

const TOKENS_PER_THOUSAND = 1000;
const CENTS_PER_DOLLAR = 100;
const FULL_PERCENT = 100;

interface UsageReadoutProps {
  label: string;
  used: number;
  budget: number | null;
}

function UsageReadout({ label, used, budget }: UsageReadoutProps) {
  const t = useTranslations("admin.spendingLimits");
  const percent =
    budget === null || budget <= 0 ? null : (used / budget) * FULL_PERCENT;
  const over = percent !== null && percent >= FULL_PERCENT;
  return (
    <Card
      padding={2}
      rounding={2}
      color={over ? "status-error-00" : "background-tint-01"}
    >
      <Section gap={1} alignItems="stretch" height="auto">
        <Section
          flexDirection="row"
          justifyContent="between"
          alignItems="center"
          height="auto"
        >
          <Text
            font="secondary-body"
            color={over ? "status-error-05" : "text-03"}
          >
            {label}
          </Text>
          {percent !== null && (
            <Text
              font="secondary-action"
              color={over ? "status-error-05" : "text-04"}
            >
              {t("row.usage.percent", { percent: Math.round(percent) })}
            </Text>
          )}
        </Section>
        {percent !== null && (
          <ProgressBar
            value={Math.min(percent, FULL_PERCENT)}
            color={over ? "red" : "blue"}
          />
        )}
      </Section>
    </Card>
  );
}

interface LimitRowEditorProps {
  limit: DraftLimit;
  error: DraftLimitError | undefined;
  /** Pool cards show what the pool has used this period. */
  showUsage: boolean;
  modelOptions: SelectOption[];
  disabled: boolean;
  onChange: (limit: DraftLimit) => void;
  onRemove: () => void;
}

export default function LimitRowEditor({
  limit,
  error,
  showUsage,
  modelOptions,
  disabled,
  onChange,
  onRemove,
}: LimitRowEditorProps) {
  const t = useTranslations("admin.spendingLimits");
  const format = useFormatter();
  const locale = useLocale();

  const periodOptions: SelectOption[] = PERIODS.map((period) => ({
    value: period,
    title: t(`row.period.options.${period}.title`),
    description: t(`row.period.options.${period}.description`),
  }));
  const saved = limit.saved;
  const savedPeriodMatches = saved !== null && saved.period === limit.period;

  return (
    <Card padding={2} rounding={3} color="background-tint-01">
      <Section gap={3} alignItems="stretch" height="auto">
        {limit.isModelRow && (
          <InputVertical
            title={t("row.model.title")}
            error={
              error === "modelRequired"
                ? t("row.errors.modelRequired")
                : undefined
            }
          >
            <InputSingleSelect
              value={limit.modelConfigurationId?.toString() ?? ""}
              onValueChange={(value) =>
                onChange({
                  ...limit,
                  modelConfigurationId: value === "" ? null : Number(value),
                })
              }
              placeholder={t("row.model.placeholder")}
              options={modelOptions}
              search
              disabled={disabled}
            />
          </InputVertical>
        )}

        <Section
          flexDirection="row"
          alignItems="end"
          justifyContent="between"
          gap={2}
          height="auto"
        >
          <Section height="auto" alignItems="stretch" gap={1}>
            <InputVertical
              title={t("row.period.title")}
              subDescription={
                savedPeriodMatches
                  ? t("row.nextReset", {
                      at: format.dateTime(new Date(saved.reset_at), {
                        dateStyle: "medium",
                        timeStyle: "short",
                        timeZone: "UTC",
                      }),
                    })
                  : undefined
              }
            >
              <InputSingleSelect
                value={limit.period}
                onValueChange={(value) => {
                  const period = PERIODS.find((p) => p === value);
                  if (period) onChange({ ...limit, period });
                }}
                defaultOption={limit.period}
                placeholder={t("row.period.title")}
                options={periodOptions}
                disabled={disabled}
              />
            </InputVertical>
          </Section>
          <Button
            icon={SvgMinusCircle}
            prominence="tertiary"
            size="sm"
            tooltip={t("row.remove.tooltip")}
            aria-label={t("row.remove.tooltip")}
            disabled={disabled}
            onClick={onRemove}
          />
        </Section>

        <Section flexDirection="row" alignItems="start" gap={2} height="auto">
          <Section height="auto" alignItems="stretch" gap={1}>
            <InputVertical title={t("row.cost.title")}>
              <InputCurrency
                value={limit.costDollars}
                onChange={(costDollars) => onChange({ ...limit, costDollars })}
                disabled={disabled}
              />
            </InputVertical>
            {showUsage && savedPeriodMatches && (
              <UsageReadout
                label={t("row.usage.spent", {
                  amount: formatCurrencyFromCents(
                    saved.used_cost_cents ?? 0,
                    locale
                  ),
                })}
                used={saved.used_cost_cents ?? 0}
                budget={
                  limit.costDollars === null
                    ? null
                    : limit.costDollars * CENTS_PER_DOLLAR
                }
              />
            )}
          </Section>
          <Section height="auto" alignItems="stretch" gap={1}>
            <InputVertical title={t("row.tokens.title")}>
              <InputNumber
                value={limit.tokenThousands}
                onChange={(tokenThousands) =>
                  onChange({ ...limit, tokenThousands })
                }
                min={1}
                plain
                suffix={t("row.tokens.suffix")}
                placeholder={t("row.tokens.placeholder")}
                disabled={disabled}
              />
            </InputVertical>
            {showUsage && savedPeriodMatches && (
              <UsageReadout
                label={t("row.usage.tokens", {
                  tokens: formatTokenCount(saved.used_tokens ?? 0, locale),
                })}
                used={saved.used_tokens ?? 0}
                budget={
                  limit.tokenThousands === null
                    ? null
                    : limit.tokenThousands * TOKENS_PER_THOUSAND
                }
              />
            )}
          </Section>
        </Section>

        <InputVertical
          title={t("row.whenReached.title")}
          description={
            limit.isModelRow
              ? t("row.whenReached.blockModel.description")
              : t("row.whenReached.blockAll.description")
          }
          error={
            error === "budgetRequired"
              ? t("row.errors.budgetRequired")
              : error === "duplicate"
                ? t("row.errors.duplicate")
                : undefined
          }
        >
          {/* TODO(evan-onyx): add the alert-only option once notifications ship. */}
          <Text font="main-ui-body" color="text-04">
            {limit.isModelRow
              ? t("row.whenReached.blockModel.title")
              : t("row.whenReached.blockAll.title")}
          </Text>
        </InputVertical>
      </Section>
    </Card>
  );
}
