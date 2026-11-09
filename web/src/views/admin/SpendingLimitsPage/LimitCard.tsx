"use client";

import { useEffect, useRef, useState } from "react";
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
import type { IconFunctionComponent, RichStr } from "@opal/types";
import {
  SvgExpand,
  SvgFold,
  SvgPlug,
  SvgPlusCircle,
  SvgUnplug,
} from "@opal/icons";
import { richNodes } from "@opal/utils";
import { formatCurrencyFromCents, formatTokenCount } from "@/lib/format";
import {
  resetSpendingLimitUsage,
  saveSpendingLimitCard,
} from "@/lib/spendingLimits/svc";
import {
  LimitAction,
  type CardPath,
  type SpendingLimit,
  type SpendingLimitCard,
} from "@/lib/spendingLimits/types";
import {
  cardSignature,
  emptyDraftLimit,
  isDraftDirty,
  toCardDraft,
  toRequests,
  validateDraft,
  withSavedFrom,
  type CardDraft,
  type DraftLimit,
} from "@/views/admin/SpendingLimitsPage/draft";
import LimitRow from "@/views/admin/SpendingLimitsPage/LimitRow";
import {
  EMPHASIS,
  cardSummaryLimits,
  useLimitSummary,
} from "@/views/admin/SpendingLimitsPage/summary";
import UsageIcon, {
  FULL_PERCENT,
} from "@/views/admin/SpendingLimitsPage/UsageIcon";

const TOKENS_PER_THOUSAND = 1000;

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
  title: string | RichStr;
  description: string | RichStr;
  icon: IconFunctionComponent;
  /** Shown while the card has no limits. */
  emptyTitle: string | RichStr;
  emptyDescription: string | RichStr;
  /** Names the card's target in the folded summary, e.g. "Group limit". */
  targetLabel: string;
  /** Leads the folded summary line, e.g. the group's name. */
  summaryPrefix?: string;
  card: SpendingLimitCard;
  /** null until the caller knows where to save, e.g. before a group is picked. */
  path: CardPath | null;
  showUsage: boolean;
  modelOptions: SelectOption[];
  /** Read-only when false: the caller can see the card but not change it. */
  canEdit: boolean;
  /** Shown in a read-only card to say why it can't be edited. */
  readOnlyNote?: string | RichStr;
  /** Content above the limits, e.g. the group the card applies to. */
  targetField?: React.ReactNode;
  /** A new card opens with one empty limit and drops on cancel. */
  isNew?: boolean;
  onCancelNew?: () => void;
  onSaved: () => void;
  /** Each new value opens the card and scrolls to it. */
  revealKey?: number;
}

export default function LimitCard({
  title,
  description,
  icon,
  emptyTitle,
  emptyDescription,
  targetLabel,
  summaryPrefix,
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
  revealKey,
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
  const [resetting, setResetting] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  function newDraft(): CardDraft {
    const loaded = toCardDraft(card);
    return isNew
      ? { ...loaded, limits: [emptyDraftLimit(false, loaded.limits)] }
      : loaded;
  }

  // A change to the stored limits replaces the draft; a refetch that only
  // moves usage keeps unsaved edits.
  const signature = cardSignature(card);
  useEffect(() => {
    setDraft(newDraft());
    setOpenModelRows(new Set());
  }, [signature]);
  useEffect(() => {
    setDraft((prev) => withSavedFrom(prev, card));
  }, [card]);

  useEffect(() => {
    if (revealKey === undefined) return;
    setExpanded(true);
    rootRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [revealKey]);

  const errors = validateDraft(draft);
  const dirty = isNew || isDraftDirty(draft, card);
  const blockLimits = card.limits.filter(
    (limit) => limit.action === LimitAction.BLOCK
  );
  const isEmpty = card.limits.length === 0;
  // A save replaces the limit rows, so it waits for a reset, and back.
  const busy = saving || resetting;
  const disabled = !canEdit || busy;

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

  async function resetUsage(cardPath: CardPath, limitId: number) {
    setResetting(true);
    try {
      await resetSpendingLimitUsage(cardPath, limitId);
      toast.success(t("row.resetUsage.done"));
      onSaved();
    } catch (error) {
      toast.error(
        t("row.resetUsage.failed", {
          error: error instanceof Error ? error.message : String(error),
        })
      );
    } finally {
      setResetting(false);
    }
  }

  function setEnabled(enabled: boolean) {
    void save(enabled, toCardDraft(card));
  }

  function rows(limits: DraftLimit[]) {
    return limits.map((limit) => {
      const savedId = limit.saved?.id;
      return (
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
          onResetUsage={
            canEdit && path !== null && savedId !== undefined
              ? () => void resetUsage(path, savedId)
              : undefined
          }
        />
      );
    });
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
        ref={rootRef}
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
  const summaryLimits = cardSummaryLimits(card);

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
                <>
                  {summaryPrefix !== undefined && (
                    <span className="font-main-ui-body">
                      {t("card.summary.prefix", { name: summaryPrefix })}
                    </span>
                  )}
                  {summarize(
                    summaryLimits,
                    inactive ? EMPHASIS.titleInactive : EMPHASIS.title
                  )}
                </>
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
              disabled={busy}
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
              <UsageIcon percent={usagePercent} />
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
            font="main-ui-action"
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
            disabled={busy}
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
      ref={rootRef}
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
                <Button prominence="secondary" disabled={busy} onClick={cancel}>
                  {t("card.cancel")}
                </Button>
                <Button
                  disabled={!dirty || errors.size > 0 || busy || path === null}
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
