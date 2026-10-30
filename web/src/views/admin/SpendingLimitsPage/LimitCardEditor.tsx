"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import {
  Button,
  Card,
  Divider,
  InputSwitch,
  Text,
  type SelectOption,
} from "@opal/components";
import { ContentAction, Section, toast } from "@opal/layouts";
import type { IconFunctionComponent } from "@opal/types";
import { SvgPlusCircle } from "@opal/icons";
import { formatCurrencyFromCents, formatTokenCount } from "@/lib/format";
import { saveSpendingLimitCard } from "@/lib/spendingLimits/svc";
import type {
  CardPath,
  SpendingLimit,
  SpendingLimitCard,
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
import LimitRowEditor from "@/views/admin/SpendingLimitsPage/LimitRowEditor";

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

interface LimitCardEditorProps {
  title: string;
  description: string;
  icon: IconFunctionComponent;
  card: SpendingLimitCard;
  path: CardPath;
  showUsage: boolean;
  modelOptions: SelectOption[];
  /** Read-only when false: the caller can see the card but not change it. */
  canEdit: boolean;
  /** Shown under a read-only card's header to say why it can't be edited. */
  readOnlyNote?: string;
  onSaved: () => void;
}

export default function LimitCardEditor({
  title,
  description,
  icon,
  card,
  path,
  showUsage,
  modelOptions,
  canEdit,
  readOnlyNote,
  onSaved,
}: LimitCardEditorProps) {
  const t = useTranslations("admin.spendingLimits");
  const [draft, setDraft] = useState<CardDraft>(() => toCardDraft(card));
  const [saving, setSaving] = useState(false);

  // A refetch after a save replaces the draft with what the server stored.
  useEffect(() => {
    setDraft(toCardDraft(card));
  }, [card]);

  const errors = validateDraft(draft);
  const dirty = isDraftDirty(draft, card);

  function updateLimit(updated: DraftLimit) {
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
    setDraft((prev) => ({
      ...prev,
      limits: [...prev.limits, emptyDraftLimit(isModelRow, prev.limits)],
    }));
  }

  async function save() {
    setSaving(true);
    try {
      await saveSpendingLimitCard(path, draft.enabled, toRequests(draft));
      toast.success(t("card.saved"));
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

  const disabled = !canEdit || saving;
  const allModelLimits = draft.limits.filter((limit) => !limit.isModelRow);
  const modelLimits = draft.limits.filter((limit) => limit.isModelRow);

  function rows(limits: DraftLimit[]) {
    return limits.map((limit) => (
      <LimitRowEditor
        key={limit.key}
        limit={limit}
        error={errors.get(limit.key)}
        showUsage={showUsage}
        modelOptions={modelOptions}
        disabled={disabled}
        onChange={updateLimit}
        onRemove={() => removeLimit(limit.key)}
      />
    ));
  }

  return (
    <Card
      border="solid"
      rounding={4}
      padding={3}
      data-testid={`spending-limit-card-${path}`}
    >
      <Section gap={3} alignItems="stretch" height="auto">
        <ContentAction
          sizePreset="main-ui"
          variant="section"
          icon={icon}
          title={title}
          description={description}
          rightChildren={
            <InputSwitch
              checked={draft.enabled}
              disabled={disabled}
              aria-label={t("card.enabled.ariaLabel", { title })}
              onCheckedChange={(checked) =>
                setDraft((prev) => ({ ...prev, enabled: checked }))
              }
            />
          }
        />
        {!canEdit && readOnlyNote && (
          <Text font="secondary-body" color="text-03">
            {readOnlyNote}
          </Text>
        )}
        {rows(allModelLimits)}
        {canEdit && (
          <Section alignItems="start" height="auto">
            <Button
              icon={SvgPlusCircle}
              prominence="secondary"
              disabled={disabled}
              onClick={() => addLimit(false)}
            >
              {t("card.addLimit")}
            </Button>
          </Section>
        )}

        <Divider />
        <Section gap={1} alignItems="start" height="auto">
          <Text font="main-ui-action" color="text-04">
            {t("card.modelBudget.title")}
          </Text>
          <Text font="secondary-body" color="text-03">
            {t("card.modelBudget.description")}
          </Text>
        </Section>
        {rows(modelLimits)}
        {canEdit && (
          <Section alignItems="start" height="auto">
            <Button
              icon={SvgPlusCircle}
              prominence="secondary"
              disabled={disabled}
              onClick={() => addLimit(true)}
            >
              {t("card.addModelBudget")}
            </Button>
          </Section>
        )}

        {draft.alertLimits.length > 0 && (
          <>
            <Divider />
            <Section gap={1} alignItems="start" height="auto">
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

        {canEdit && (
          <>
            <Divider />
            <Section
              flexDirection="row"
              justifyContent="end"
              gap={1}
              height="auto"
            >
              <Button
                prominence="secondary"
                disabled={!dirty || saving}
                onClick={() => setDraft(toCardDraft(card))}
              >
                {t("card.cancel")}
              </Button>
              <Button
                disabled={!dirty || errors.size > 0 || saving}
                onClick={() => void save()}
              >
                {t("card.save")}
              </Button>
            </Section>
          </>
        )}
      </Section>
    </Card>
  );
}
