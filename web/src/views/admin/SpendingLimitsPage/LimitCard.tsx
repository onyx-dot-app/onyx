"use client";

import { useEffect, useState } from "react";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import {
  Button,
  Card,
  Divider,
  Fold,
  IconContainer,
  Text,
  type SelectOption,
} from "@opal/components";
import { Content, Section, toast } from "@opal/layouts";
import type { IconFunctionComponent } from "@opal/types";
import {
  SvgAlertCircle,
  SvgExpand,
  SvgFold,
  SvgPlug,
  SvgPlusCircle,
  SvgProgressCircle,
  SvgUnplug,
} from "@opal/icons";
import { richNodes } from "@opal/utils";
import { formatCurrencyFromCents, formatTokenCount } from "@/lib/format";
import { saveSpendingLimitCard } from "@/lib/spendingLimits/svc";
import {
  LimitAction,
  type CardPath,
  type SpendingLimit,
  type SpendingLimitCard,
} from "@/lib/spendingLimits/types";
import {
  emptyDraftLimit,
  isDraftDirty,
  toCardDraft,
  toRequests,
  validateDraft,
  type CardDraft,
  type DraftLimit,
} from "@/views/admin/SpendingLimitsPage/draft";
import LimitRow from "@/views/admin/SpendingLimitsPage/LimitRow";
import {
  EMPHASIS,
  useLimitSummary,
} from "@/views/admin/SpendingLimitsPage/summary";

const TOKENS_PER_THOUSAND = 1000;
const FULL_PERCENT = 100;

interface AlertLimitRowProps {
  limit: SpendingLimit;
}

/** Alert-only limits come from the API; the page shows them unchanged. */
function AlertLimitRow({ limit }: AlertLimitRowProps) {
  const t = useTranslations("admin.spendingLimits");
  const locale = useLocale();
  const period = t(`row.period.options.${limit.period}.title`);
  const target =
    limit.threshold_percent !== null
      ? t("alerts.percent", { percent: limit.threshold_percent })
      : [
          limit.cost_budget_cents !== null
            ? formatCurrencyFromCents(limit.cost_budget_cents, locale)
            : null,
          limit.token_budget !== null
            ? t("alerts.tokens", {
                tokens: formatTokenCount(
                  limit.token_budget * TOKENS_PER_THOUSAND,
                  locale
                ),
              })
            : null,
        ]
          .filter((part): part is string => part !== null)
          .join(" · ");
  return (
    <Text font="secondary-body" color="text-03">
      {t("alerts.row", {
        model: limit.model_name ?? t("alerts.allModels"),
        period,
        target,
      })}
    </Text>
  );
}

/** The largest share of any budget used this period, as a percent. */
function highestUsagePercent(limits: SpendingLimit[]): number | null {
  const shares = limits.flatMap((limit) => [
    limit.cost_budget_cents && limit.used_cost_cents !== null
      ? limit.used_cost_cents / limit.cost_budget_cents
      : null,
    limit.token_budget && limit.used_tokens !== null
      ? limit.used_tokens / (limit.token_budget * TOKENS_PER_THOUSAND)
      : null,
  ]);
  const known = shares.filter((share): share is number => share !== null);
  return known.length === 0 ? null : Math.max(...known) * FULL_PERCENT;
}

function InsetDivider() {
  return (
    <Section
      width="auto"
      gap={0}
      alignItems="stretch"
      height="auto"
      className="mx-2"
    >
      <Divider paddingParallel={0} paddingPerpendicular={0} />
    </Section>
  );
}

interface LimitCardProps {
  title: string;
  description: string;
  icon: IconFunctionComponent;
  /** Shown while the card has no limits. */
  emptyTitle: string;
  emptyDescription: string;
  /** Names the card's target in the folded summary, e.g. "Group: Design". */
  targetLabel: string;
  card: SpendingLimitCard;
  /** null until the caller knows where to save, e.g. before a group is picked. */
  path: CardPath | null;
  showUsage: boolean;
  modelOptions: SelectOption[];
  /** Read-only when false: the caller can see the card but not change it. */
  canEdit: boolean;
  /** Shown in a read-only card to say why it can't be edited. */
  readOnlyNote?: string;
  /** Content above the limits, e.g. the group the card applies to. */
  targetField?: React.ReactNode;
  /** A new card opens with one empty limit and drops on cancel. */
  isNew?: boolean;
  onCancelNew?: () => void;
  onSaved: () => void;
}

export default function LimitCard({
  title,
  description,
  icon,
  emptyTitle,
  emptyDescription,
  targetLabel,
  card,
  path,
  showUsage,
  modelOptions,
  canEdit,
  readOnlyNote,
  targetField,
  isNew = false,
  onCancelNew,
  onSaved,
}: LimitCardProps) {
  const t = useTranslations("admin.spendingLimits");
  const format = useFormatter();
  const summarize = useLimitSummary();
  const [draft, setDraft] = useState<CardDraft>(() => newDraft());
  const [expanded, setExpanded] = useState(isNew);
  const [openModelRows, setOpenModelRows] = useState<Set<number>>(
    () => new Set()
  );
  // New rows hold their errors back until edited.
  const [editedRows, setEditedRows] = useState<Set<number>>(() => new Set());
  const [saving, setSaving] = useState(false);

  function newDraft(): CardDraft {
    const loaded = toCardDraft(card);
    return isNew
      ? { ...loaded, limits: [emptyDraftLimit(false, loaded.limits)] }
      : loaded;
  }

  // A refetch after a save replaces the draft with what the server stored.
  useEffect(() => {
    setDraft(newDraft());
    setOpenModelRows(new Set());
  }, [card]);

  const errors = validateDraft(draft);
  const dirty = isNew || isDraftDirty(draft, card);
  const blockLimits = card.limits.filter(
    (limit) => limit.action === LimitAction.BLOCK
  );
  const isEmpty = card.limits.length === 0;
  const disabled = !canEdit || saving;

  function updateLimit(updated: DraftLimit) {
    setEditedRows((prev) => new Set(prev).add(updated.key));
    setDraft((prev) => ({
      ...prev,
      limits: prev.limits.map((limit) =>
        limit.key === updated.key ? updated : limit
      ),
    }));
  }

  function removeLimit(key: number) {
    setDraft((prev) => ({
      ...prev,
      limits: prev.limits.filter((limit) => limit.key !== key),
    }));
  }

  function addLimit(isModelRow: boolean) {
    const added = emptyDraftLimit(isModelRow, draft.limits);
    setDraft((prev) => ({ ...prev, limits: [...prev.limits, added] }));
    if (isModelRow) {
      setOpenModelRows((prev) => new Set(prev).add(added.key));
    }
  }

  function openModelRow(key: number) {
    setOpenModelRows((prev) => new Set(prev).add(key));
  }

  function startFromEmpty() {
    setDraft((prev) => ({
      ...prev,
      limits: [emptyDraftLimit(false, prev.limits)],
    }));
    setExpanded(true);
  }

  function cancel() {
    if (isNew) {
      onCancelNew?.();
      return;
    }
    setDraft(toCardDraft(card));
    setOpenModelRows(new Set());
    setExpanded(false);
  }

  async function save(enabled: boolean, draftToSave: CardDraft) {
    if (path === null) return;
    setSaving(true);
    try {
      await saveSpendingLimitCard(path, enabled, toRequests(draftToSave));
      toast.success(t("card.saved"));
      setExpanded(false);
      onSaved();
    } catch (error) {
      toast.error(
        t("card.saveFailed", {
          error: error instanceof Error ? error.message : String(error),
        })
      );
    } finally {
      setSaving(false);
    }
  }

  function setEnabled(enabled: boolean) {
    void save(enabled, toCardDraft(card));
  }

  function rows(limits: DraftLimit[]) {
    return limits.map((limit) => (
      <LimitRow
        key={limit.key}
        limit={limit}
        error={
          limit.saved !== null || editedRows.has(limit.key)
            ? errors.get(limit.key)
            : undefined
        }
        showUsage={showUsage}
        modelOptions={modelOptions}
        open={openModelRows.has(limit.key)}
        disabled={disabled}
        onOpen={() => openModelRow(limit.key)}
        onChange={updateLimit}
        onRemove={() => removeLimit(limit.key)}
      />
    ));
  }

  function addButton(label: string, isModelRow: boolean) {
    if (!canEdit) return null;
    return (
      <Section
        width="auto"
        gap={0}
        alignItems="start"
        height="auto"
        className="mx-2 mt-4"
      >
        <Button
          icon={SvgPlusCircle}
          prominence="secondary"
          disabled={disabled}
          onClick={() => addLimit(isModelRow)}
        >
          {label}
        </Button>
      </Section>
    );
  }

  const testId = `spending-limit-card-${path ?? "new"}`;

  if (isEmpty && !expanded) {
    return (
      <Card
        padding={2}
        rounding={4}
        border="solid"
        color="background-tint-01"
        data-testid={testId}
      >
        <Section gap={0} flexDirection="row" alignItems="start" height="auto">
          <Section
            flexDirection="row"
            alignItems="start"
            justifyContent="start"
            gap={1}
            padding={2}
            height="auto"
          >
            <IconContainer icon={icon} />
            <Section gap={0} alignItems="start" height="auto">
              <Text font="main-ui-body" color="text-03">
                {emptyTitle}
              </Text>
              <Text font="secondary-body" color="text-03">
                {emptyDescription}
              </Text>
            </Section>
          </Section>
          {canEdit && (
            <Section gap={0} width="fit" height="auto" padding={2}>
              <Button icon={SvgPlusCircle} onClick={startFromEmpty}>
                {t("card.addLimit")}
              </Button>
            </Section>
          )}
        </Section>
      </Card>
    );
  }

  const allModelLimits = draft.limits.filter((limit) => !limit.isModelRow);
  const modelLimits = draft.limits.filter((limit) => limit.isModelRow);
  const savedModelBudgets = blockLimits.filter(
    (limit) => limit.model_configuration_id !== null
  ).length;
  const usagePercent = showUsage ? highestUsagePercent(blockLimits) : null;
  const nextReset = blockLimits
    .map((limit) => new Date(limit.reset_at))
    .sort((a, b) => a.getTime() - b.getTime())[0];
  const inactive = !card.enabled;
  const summaryLimits = blockLimits
    .filter((limit) => limit.model_configuration_id === null)
    .map((limit) => ({
      period: limit.period,
      costCents: limit.cost_budget_cents,
      tokenThousands: limit.token_budget,
    }));

  const foldedHeader = (
    <>
      <Section
        flexDirection="row"
        alignItems="start"
        justifyContent="start"
        gap={1}
        padding={2}
        height="auto"
      >
        <IconContainer icon={icon} />
        <Section
          alignItems="start"
          justifyContent="start"
          gap={1}
          height="auto"
          className="max-w-120"
        >
          <Section gap={0} alignItems="start" height="auto">
            <Text
              font="main-ui-muted"
              color={inactive ? "text-02" : "text-03"}
              strikethrough={inactive}
            >
              {richNodes(
                summarize(
                  summaryLimits,
                  inactive ? EMPHASIS.titleInactive : EMPHASIS.title
                )
              )}
            </Text>
          </Section>
          <Section gap={0} alignItems="start" height="auto">
            <Text font="secondary-body" color="text-03">
              {savedModelBudgets > 0
                ? t("card.summary.target", {
                    target: targetLabel,
                    count: savedModelBudgets,
                  })
                : targetLabel}
            </Text>
            <Text font="secondary-body" color="text-03">
              {inactive || nextReset === undefined
                ? t("card.summary.inactive")
                : t("card.summary.nextReset", {
                    at: format.dateTime(nextReset, {
                      weekday: "short",
                      hour: "2-digit",
                      minute: "2-digit",
                    }),
                  })}
            </Text>
          </Section>
        </Section>
      </Section>
      <Section
        gap={0}
        alignItems="end"
        justifyContent="between"
        width="fit"
        height="auto"
      >
        <Section gap={0} flexDirection="row" width="fit" height="auto">
          {inactive && canEdit && (
            <Button
              rightIcon={SvgPlug}
              prominence="tertiary"
              disabled={saving}
              onClick={() => setEnabled(true)}
            >
              {t("card.reenable")}
            </Button>
          )}
          <Section gap={0} width="fit" height="auto" padding={1}>
            <Button
              icon={SvgExpand}
              prominence="tertiary"
              size="md"
              tooltip={t("card.expand.tooltip")}
              aria-label={t("card.expand.tooltip")}
              aria-expanded={false}
              onClick={() => setExpanded(true)}
            />
          </Section>
        </Section>
        {usagePercent !== null && !inactive && (
          <Section gap={0} width="auto" height="auto" className="mx-1 mb-1">
            <Section
              flexDirection="row"
              gap={1}
              padding={1}
              width="fit"
              height="auto"
            >
              <Section gap={0} width="fit" height="auto">
                <Text font="main-ui-muted" color="text-03">
                  {richNodes(
                    t.rich("card.summary.used", {
                      percent: Math.round(usagePercent),
                      b: (chunks) => (
                        <span className={EMPHASIS.title}>{chunks}</span>
                      ),
                    })
                  )}
                </Text>
              </Section>
              <Section
                gap={0}
                width={1.25}
                height={1.25}
                padding={0.5}
                className={
                  usagePercent >= FULL_PERCENT
                    ? "text-status-error-05"
                    : "text-theme-blue-05"
                }
              >
                {usagePercent >= FULL_PERCENT ? (
                  <SvgAlertCircle size={16} />
                ) : (
                  <SvgProgressCircle size={16} value={usagePercent} />
                )}
              </Section>
            </Section>
          </Section>
        )}
      </Section>
    </>
  );

  const expandedHeader = (
    <>
      <Section gap={0} alignItems="start" padding={2} height="auto">
        <Section gap={0} alignItems="start" height="auto" className="max-w-120">
          <Content
            sizePreset="main-ui"
            variant="section"
            icon={icon}
            title={title}
            description={description}
          />
        </Section>
      </Section>
      <Section
        flexDirection="row"
        gap={1}
        padding={1}
        width="fit"
        height="auto"
      >
        {canEdit && !isNew && !isEmpty && !inactive && (
          <Button
            icon={SvgUnplug}
            prominence="tertiary"
            size="md"
            tooltip={t("card.disable.tooltip")}
            aria-label={t("card.disable.tooltip")}
            disabled={saving}
            onClick={() => setEnabled(false)}
          />
        )}
        <Button
          icon={SvgFold}
          prominence="tertiary"
          size="md"
          tooltip={t("card.collapse.tooltip")}
          aria-label={t("card.collapse.tooltip")}
          aria-expanded
          onClick={() => (isNew || isEmpty ? cancel() : setExpanded(false))}
        />
      </Section>
    </>
  );

  return (
    <Card
      padding={0}
      rounding={4}
      border="solid"
      color={
        inactive && !expanded ? "background-tint-02" : "background-tint-00"
      }
      data-testid={testId}
    >
      <Section
        gap={0}
        flexDirection="row"
        alignItems="stretch"
        justifyContent="between"
        padding={2}
        height="auto"
      >
        {expanded ? expandedHeader : foldedHeader}
      </Section>
      <Fold open={expanded}>
        <Section gap={0} alignItems="stretch" height="auto">
          <Section
            width="auto"
            gap={0}
            alignItems="stretch"
            height="auto"
            className="mx-2 mb-2"
          >
            {!canEdit && readOnlyNote && (
              <Section
                width="auto"
                gap={0}
                alignItems="start"
                height="auto"
                className="mx-2 mb-4"
              >
                <Text font="secondary-body" color="text-03">
                  {readOnlyNote}
                </Text>
              </Section>
            )}
            {targetField && (
              <>
                <Section
                  width="auto"
                  gap={0}
                  alignItems="stretch"
                  height="auto"
                  className="mx-2 mt-2 mb-4"
                >
                  {targetField}
                </Section>
                <InsetDivider />
                <Section gap={0} height="auto" className="mb-2" />
              </>
            )}
            <Section gap={2} alignItems="stretch" height="auto">
              {rows(allModelLimits)}
            </Section>
            {addButton(t("card.addLimit"), false)}

            <Section
              alignItems="stretch"
              gap={0}
              height="auto"
              className="my-4"
            >
              <InsetDivider />
            </Section>
            <Section
              width="auto"
              gap={0}
              alignItems="start"
              height="auto"
              className="mx-2"
            >
              <Text font="main-ui-action" color="text-04">
                {t("card.modelBudget.title")}
              </Text>
              <Text font="secondary-body" color="text-03">
                {t("card.modelBudget.description")}
              </Text>
            </Section>
            {modelLimits.length > 0 && (
              <Section
                gap={2}
                alignItems="stretch"
                height="auto"
                className="mt-2"
              >
                {rows(modelLimits)}
              </Section>
            )}
            {addButton(t("card.addModelBudget"), true)}

            {draft.alertLimits.length > 0 && (
              <>
                <Section
                  alignItems="stretch"
                  gap={0}
                  height="auto"
                  className="my-4"
                >
                  <InsetDivider />
                </Section>
                <Section
                  width="auto"
                  gap={0}
                  alignItems="start"
                  height="auto"
                  className="mx-2"
                >
                  <Text font="main-ui-action" color="text-04">
                    {t("alerts.title")}
                  </Text>
                  <Text font="secondary-body" color="text-03">
                    {t("alerts.description")}
                  </Text>
                  {draft.alertLimits.map((limit) => (
                    <AlertLimitRow key={limit.id} limit={limit} />
                  ))}
                </Section>
              </>
            )}
          </Section>
          {canEdit && (
            <>
              <Section
                alignItems="stretch"
                width="auto"
                gap={0}
                height="auto"
                className="mx-2 mt-2"
              >
                <InsetDivider />
              </Section>
              <Section
                flexDirection="row"
                justifyContent="end"
                gap={2}
                padding={4}
                height="auto"
              >
                <Button
                  prominence="secondary"
                  disabled={saving}
                  onClick={cancel}
                >
                  {t("card.cancel")}
                </Button>
                <Button
                  disabled={
                    !dirty || errors.size > 0 || saving || path === null
                  }
                  onClick={() => void save(draft.enabled, draft)}
                >
                  {isNew ? t("card.create") : t("card.save")}
                </Button>
              </Section>
            </>
          )}
        </Section>
      </Fold>
    </Card>
  );
}
