"use client";

import { useFormatter, useTranslations } from "next-intl";
import {
  Button,
  Card,
  Divider,
  IconContainer,
  InputCurrency,
  InputNumber,
  InputSingleSelect,
  Text,
  type SelectOption,
} from "@opal/components";
import { InputErrorText, InputVertical, Section } from "@opal/layouts";
import {
  SvgAlertCircle,
  SvgMinusCircle,
  SvgPenSmall,
  SvgProgressCircle,
  SvgSlash,
} from "@opal/icons";
import { richNodes } from "@opal/utils";
import type { RichNodes } from "@opal/types";
import { LimitAction, PERIODS } from "@/lib/spendingLimits/types";
import type {
  DraftLimit,
  DraftLimitError,
} from "@/views/admin/SpendingLimitsPage/draft";
import {
  EMPHASIS,
  useLimitSummary,
} from "@/views/admin/SpendingLimitsPage/summary";

const TOKENS_PER_THOUSAND = 1000;
const CENTS_PER_DOLLAR = 100;
const FULL_PERCENT = 100;

interface UsageSummaryProps {
  amount: RichNodes;
  used: number;
  budget: number | null;
}

/** Usage so far this period against one budget. */
function UsageSummary({ amount, used, budget }: UsageSummaryProps) {
  const t = useTranslations("admin.spendingLimits.row.usage");
  const percent =
    budget === null || budget <= 0 ? null : (used / budget) * FULL_PERCENT;
  const over = percent !== null && percent >= FULL_PERCENT;
  return (
    <Card
      padding={2}
      rounding={2}
      color={over ? "status-error-00" : "background-tint-00"}
    >
      <Section flexDirection="row" alignItems="center" gap={1} height="auto">
        <Section gap={0} alignItems="start" height="auto">
          <Text
            font="secondary-body"
            color={over ? "status-error-05" : "text-03"}
          >
            {amount}
          </Text>
        </Section>
        {percent !== null && (
          <>
            <Section gap={0} width="fit" height="auto">
              <Text
                font="main-ui-action"
                color={over ? "status-error-05" : "text-04"}
                wordWrap="whitespace-nowrap"
              >
                {t("percent", { percent: Math.round(percent) })}
              </Text>
            </Section>
            <Section
              gap={0}
              width={1.25}
              height={1.25}
              padding={0.5}
              className={over ? "text-status-error-05" : "text-theme-blue-05"}
            >
              {over ? (
                <SvgAlertCircle size={16} />
              ) : (
                <SvgProgressCircle size={16} value={percent} />
              )}
            </Section>
          </>
        )}
      </Section>
    </Card>
  );
}

interface RowActionsProps {
  onEdit?: () => void;
  onRemove: () => void;
  disabled: boolean;
}

function RowActions({ onEdit, onRemove, disabled }: RowActionsProps) {
  const t = useTranslations("admin.spendingLimits.row");
  return (
    <Section
      flexDirection="row"
      justifyContent="end"
      gap={1}
      padding={1}
      width="fit"
      height="auto"
    >
      {onEdit && (
        <Button
          icon={SvgPenSmall}
          prominence="tertiary"
          size="md"
          tooltip={t("edit.tooltip")}
          aria-label={t("edit.tooltip")}
          onClick={onEdit}
        />
      )}
      <Button
        icon={SvgMinusCircle}
        prominence="tertiary"
        size="md"
        tooltip={t("remove.tooltip")}
        aria-label={t("remove.tooltip")}
        disabled={disabled}
        onClick={onRemove}
      />
    </Section>
  );
}

interface LimitRowProps {
  limit: DraftLimit;
  error: DraftLimitError | undefined;
  /** Pool cards show what the pool has used this period. */
  showUsage: boolean;
  modelOptions: SelectOption[];
  /** A model row shows a one-line summary until it is opened. */
  open: boolean;
  disabled: boolean;
  onOpen: () => void;
  onChange: (limit: DraftLimit) => void;
  onRemove: () => void;
}

export default function LimitRow({
  limit,
  error,
  showUsage,
  modelOptions,
  open,
  disabled,
  onOpen,
  onChange,
  onRemove,
}: LimitRowProps) {
  const t = useTranslations("admin.spendingLimits");
  const format = useFormatter();
  const summarize = useLimitSummary();

  const model = modelOptions.find(
    (option) => option.value === String(limit.modelConfigurationId)
  );
  const saved = limit.saved;
  const savedPeriodMatches = saved !== null && saved.period === limit.period;
  const costCents =
    limit.costDollars === null
      ? null
      : Math.round(limit.costDollars * CENTS_PER_DOLLAR);
  const tokenBudget =
    limit.tokenThousands === null
      ? null
      : limit.tokenThousands * TOKENS_PER_THOUSAND;
  const blockTitle = limit.isModelRow
    ? t("row.whenReached.blockModel.title")
    : t("row.whenReached.blockAll.title");

  if (limit.isModelRow && !open) {
    return (
      <Card padding={0} rounding={3} color="background-tint-01">
        <Section gap={0} flexDirection="row" alignItems="start" height="auto">
          <Section
            flexDirection="row"
            alignItems="start"
            gap={1}
            padding={2}
            height="auto"
          >
            {model?.icon && <IconContainer icon={model.icon} />}
            <Section gap={0} alignItems="start" height="auto">
              <Text font="main-ui-body" color="text-04">
                {model?.title ?? ""}
              </Text>
              <Text font="secondary-body" color="text-03">
                {richNodes(
                  <>
                    {summarize(
                      [
                        {
                          period: limit.period,
                          costCents,
                          tokenThousands: limit.tokenThousands,
                        },
                      ],
                      EMPHASIS.secondary
                    )}
                    {t("card.summary.separator")}
                    {t("row.whenReached.blockModel.summary")}
                  </>
                )}
              </Text>
            </Section>
          </Section>
          <RowActions
            onEdit={disabled ? undefined : onOpen}
            onRemove={onRemove}
            disabled={disabled}
          />
        </Section>
      </Card>
    );
  }

  const periodOptions: SelectOption[] = PERIODS.map((period) => ({
    value: period,
    title: t(`row.period.options.${period}.title`),
    description: t(`row.period.options.${period}.description`),
  }));
  const usageVisible = showUsage && savedPeriodMatches;
  const costOver =
    usageVisible &&
    costCents !== null &&
    costCents > 0 &&
    (saved.used_cost_cents ?? 0) >= costCents;
  const tokensOver =
    usageVisible &&
    tokenBudget !== null &&
    tokenBudget > 0 &&
    (saved.used_tokens ?? 0) >= tokenBudget;
  const blockedMessage = limit.isModelRow
    ? t("row.usage.blocked.model")
    : t("row.usage.blocked.all");
  const mono = (chunks: React.ReactNode) => (
    <span className="font-main-ui-mono">{chunks}</span>
  );

  return (
    <Card padding={2} rounding={3} color="background-tint-01">
      <Section gap={4} alignItems="stretch" height="auto">
        {limit.isModelRow && (
          <Section flexDirection="row" alignItems="start" gap={1} height="auto">
            <Section alignItems="stretch" gap={1} height="auto">
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
              {error === "modelRequired" && (
                <InputErrorText>{t("row.errors.modelRequired")}</InputErrorText>
              )}
            </Section>
            <RowActions onRemove={onRemove} disabled={disabled} />
          </Section>
        )}

        <Section
          flexDirection="row"
          wrap
          alignItems="start"
          gap={1}
          height="auto"
        >
          <Section
            gap={0}
            width="auto"
            height="auto"
            alignItems="stretch"
            className="min-w-70 flex-1"
          >
            <Section alignItems="stretch" gap={1} height="auto">
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
              <Section gap={0} alignItems="start" height="auto">
                <Text font="secondary-body" color="text-03">
                  {t(`row.period.options.${limit.period}.description`)}
                </Text>
              </Section>
              {error === "duplicate" && (
                <InputErrorText>{t("row.errors.duplicate")}</InputErrorText>
              )}
            </Section>
          </Section>
          <Section
            gap={0}
            flexDirection="row"
            alignItems="start"
            justifyContent="end"
            width="auto"
            height="auto"
            className="min-w-70 flex-1"
          >
            {savedPeriodMatches && (
              <Card padding={2} rounding={2} color="background-tint-00">
                <Section
                  flexDirection="row"
                  justifyContent="between"
                  gap={1}
                  height="auto"
                >
                  <Text font="secondary-body" color="text-03">
                    {t("row.nextReset")}
                  </Text>
                  <Text font="secondary-action" color="text-03">
                    {format.dateTime(new Date(saved.reset_at), {
                      year: "numeric",
                      month: "2-digit",
                      day: "2-digit",
                      weekday: "short",
                      hour: "2-digit",
                      minute: "2-digit",
                      hourCycle: "h23",
                      timeZone: "UTC",
                      timeZoneName: "short",
                    })}
                  </Text>
                </Section>
              </Card>
            )}
            {!limit.isModelRow && (
              <RowActions onRemove={onRemove} disabled={disabled} />
            )}
          </Section>
        </Section>

        <Divider paddingParallel={0} paddingPerpendicular={0} />

        <Section gap={1} alignItems="stretch" height="auto">
          <Section
            flexDirection="row"
            wrap
            alignItems="start"
            gap={1}
            height="auto"
          >
            <Section
              width="auto"
              height="auto"
              alignItems="stretch"
              gap={1}
              className="min-w-70 flex-1"
            >
              <InputVertical title={t("row.cost.title")}>
                <InputCurrency
                  value={limit.costDollars}
                  onChange={(costDollars) =>
                    onChange({ ...limit, costDollars })
                  }
                  disabled={disabled}
                />
              </InputVertical>
              {usageVisible && (
                <UsageSummary
                  amount={richNodes(
                    t.rich("row.usage.spent", {
                      amount: format.number(
                        (saved.used_cost_cents ?? 0) / CENTS_PER_DOLLAR,
                        { style: "currency", currency: "USD" }
                      ),
                      mono,
                    })
                  )}
                  used={saved.used_cost_cents ?? 0}
                  budget={costCents}
                />
              )}
            </Section>
            <Section
              width="auto"
              height="auto"
              alignItems="stretch"
              gap={1}
              className="min-w-70 flex-1"
            >
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
              {usageVisible && (
                <UsageSummary
                  amount={richNodes(
                    t.rich("row.usage.tokens", {
                      tokens: format.number(saved.used_tokens ?? 0, {
                        notation: "compact",
                      }),
                      mono,
                    })
                  )}
                  used={saved.used_tokens ?? 0}
                  budget={tokenBudget}
                />
              )}
            </Section>
          </Section>
          {(costOver || tokensOver) && (
            <Text font="secondary-body" color="status-error-05">
              {blockedMessage}
            </Text>
          )}
          {error === "budgetRequired" && (
            <InputErrorText>{t("row.errors.budgetRequired")}</InputErrorText>
          )}
        </Section>

        <InputVertical
          title={t("row.whenReached.title")}
          subDescription={
            limit.isModelRow
              ? t("row.whenReached.blockModel.description")
              : t("row.whenReached.blockAll.description")
          }
        >
          {/* TODO(evan-onyx): add the alert-only option once notifications ship. */}
          <InputSingleSelect
            value={LimitAction.BLOCK}
            placeholder={t("row.whenReached.title")}
            options={[
              { value: LimitAction.BLOCK, title: blockTitle, icon: SvgSlash },
            ]}
            disabled={disabled}
          />
        </InputVertical>
      </Section>
    </Card>
  );
}
