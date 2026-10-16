"use client";

import type { RichStr } from "@opal/types";
import { windowCoversAllHistory } from "@/lib/connectors/edit/window";
import { useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import {
  BasicModalFooter,
  Button,
  Card,
  InputSwitch,
  MessageCard,
  Modal,
  SelectCard,
  Tag,
  Text,
} from "@opal/components";
import { Content, ContentAction, Section } from "@opal/layouts";
import { IconLoader } from "@opal/loaders";
import { SvgCheckSquare, SvgRefreshCw } from "@opal/icons";
import {
  applyBlockOf,
  buildApplyRequest,
  resolvedSteps,
  canAddStep,
  initialChoices,
  type EditPlanChoices,
} from "@/lib/connectors/edit/choices";
import type { ApplyEditOutcome } from "@/lib/connectors/edit/svc";
import type {
  ConnectorEditApplyRequest,
  ConnectorEditPlanResponse,
  CredentialPath,
  EditCheckResult,
  EditNote,
  EditPlan,
  EditStep,
  ProposedPairingValidation,
  ReconciliationOption,
} from "@/lib/connectors/edit/types";
import {
  CheckLineGroups,
  type CheckLine,
} from "@/views/admin/connectors/AddConnectorPage/components/CredentialChecksCard";

export interface EditPlanModalProps {
  planResponse: ConnectorEditPlanResponse;
  onApply: (request: ConnectorEditApplyRequest) => Promise<ApplyEditOutcome>;
  /** Plans the same proposal again; the parent shows the new plan. */
  onReplan: () => Promise<void>;
  onClose: () => void;
}

interface StepCardProps {
  step: EditStep;
  dropped: boolean;
  disabled: boolean;
  onDroppedChange: (dropped: boolean) => void;
}

function StepCard({ step, dropped, disabled, onDroppedChange }: StepCardProps) {
  const t = useTranslations("admin.connectorEdit.plan.steps");
  const format = useFormatter();
  const title = t(`kind.${step.kind}.title`);
  return (
    <Card
      border="solid"
      padding={3}
      rounding={3}
      data-testid={`edit-plan-step-${step.kind}`}
    >
      <Section gap={2} alignItems="stretch" height="fit">
        <ContentAction
          title={title}
          description={t(`kind.${step.kind}.description`)}
          sizePreset="main-ui"
          variant="section"
          tag={
            step.required
              ? { title: t("required.label"), color: "amber" }
              : { title: t("optional.label"), color: "gray" }
          }
          rightChildren={
            step.required ? undefined : (
              <InputSwitch
                checked={!dropped}
                disabled={disabled}
                aria-label={t("include.ariaLabel", { step: title })}
                onCheckedChange={(checked) => onDroppedChange(!checked)}
              />
            )
          }
        />
        <Section flexDirection="row" justifyContent="start" gap={1} wrap>
          {step.reasons.map((reason) => (
            <Tag key={reason} title={t(`reason.${reason}`)} color="blue" />
          ))}
        </Section>
        {step.field_names.length > 0 && (
          <Text font="secondary-body" color="text-03">
            {t("fields", { fields: step.field_names.join(", ") })}
          </Text>
        )}
        {step.backfill !== null && (
          <Text font="secondary-body" color="text-03">
            {windowCoversAllHistory(step.backfill.window_start)
              ? t("windowFromStart", {
                  end: format.dateTime(new Date(step.backfill.window_end), {
                    dateStyle: "medium",
                    timeStyle: "short",
                  }),
                })
              : t("window", {
                  start: format.dateTime(new Date(step.backfill.window_start), {
                    dateStyle: "medium",
                    timeStyle: "short",
                  }),
                  end: format.dateTime(new Date(step.backfill.window_end), {
                    dateStyle: "medium",
                    timeStyle: "short",
                  }),
                })}
          </Text>
        )}
      </Section>
    </Card>
  );
}

interface ChoiceCardProps {
  selected: boolean;
  title: string | RichStr;
  description: string | RichStr;
  disabled: boolean;
  onSelect: () => void;
}

function ChoiceCard({
  selected,
  title,
  description,
  disabled,
  onSelect,
}: ChoiceCardProps) {
  return (
    <SelectCard
      state={selected ? "selected" : "empty"}
      padding={3}
      rounding={3}
      role="radio"
      aria-checked={selected}
      aria-label={typeof title === "string" ? title : title.raw}
      disabled={disabled}
      onClick={onSelect}
    >
      <Content
        title={title}
        description={description}
        sizePreset="main-ui"
        variant="section"
        color="interactive"
      />
    </SelectCard>
  );
}

function CheckFailures({
  results,
  variant,
}: {
  results: EditCheckResult[];
  variant: "error" | "warning";
}) {
  return (
    <>
      {results.map((result) => (
        <MessageCard
          key={result.check_id}
          variant={variant}
          title={result.display_name}
          description={result.remediation ?? result.message}
        />
      ))}
    </>
  );
}

// The validation section shows this note under the checks it is about.
const CHECKS_STILL_RUNNING_NOTE = "checks_still_running";

type ValidationOutcome = "failed" | "warnings" | "incomplete" | "passed";

function validationOutcome(
  validation: ProposedPairingValidation,
  blocksApply: boolean
): ValidationOutcome {
  if (blocksApply) return "failed";
  if (
    validation.check_results.some(
      (result) =>
        result.status === "failed" || result.status === "indeterminate"
    )
  )
    return "warnings";
  if (validation.unfinished_check_ids.length > 0) return "incomplete";
  return "passed";
}

interface ValidationSectionProps {
  plan: EditPlan;
  validation: ProposedPairingValidation;
  blocksApply: boolean;
  stillRunningNote: EditNote | undefined;
}

/** Every check of the blocking validation, as the add-connector page lists them. */
function ValidationSection({
  plan,
  validation,
  blocksApply,
  stillRunningNote,
}: ValidationSectionProps) {
  const t = useTranslations("admin.connectorEdit.plan.validation");
  const outcome = validationOutcome(validation, blocksApply);
  // An unfinished check has only its ID. A dry run of it, if any, names it.
  const unfinished: CheckLine[] = validation.unfinished_check_ids.flatMap(
    (checkId): CheckLine[] => {
      const dryRuns = plan.dry_run_results.filter(
        (result) => result.check_id === checkId
      );
      const known: Array<
        Pick<CheckLine, "capability" | "display_name" | "required">
      > =
        dryRuns.length > 0
          ? dryRuns
          : [
              {
                capability: "indexing",
                display_name: checkId,
                required: false,
              },
            ];
      return known.map((check) => ({
        capability: check.capability,
        check_id: checkId,
        display_name: check.display_name,
        required: check.required,
        message: "",
        remediation: null,
        docs_link: null,
        state: "pending",
      }));
    }
  );
  const lines: CheckLine[] = [
    ...validation.check_results.map((result) => ({
      ...result,
      state: result.status,
    })),
    ...unfinished,
  ];

  return (
    <Section gap={2} alignItems="stretch" height="fit">
      <Content
        title={t(`outcome.${outcome}.title`)}
        description={t(`outcome.${outcome}.description`)}
        sizePreset="main-ui"
        variant="section"
      />
      {validation.validation_error !== null && (
        <MessageCard
          variant="error"
          title={t("error.title")}
          description={validation.validation_error}
        />
      )}
      {lines.length > 0 && <CheckLineGroups lines={lines} />}
      {stillRunningNote !== undefined && (
        <MessageCard variant="info" title={stillRunningNote.message} />
      )}
    </Section>
  );
}

/**
 * The plan for an edit: what apply will do and why, the notes and the
 * validation result, the choices the admin must or can make, and Apply.
 */
export default function EditPlanModal({
  planResponse,
  onApply,
  onReplan,
  onClose,
}: EditPlanModalProps) {
  const t = useTranslations("admin.connectorEdit.plan");
  const { plan } = planResponse;
  const [choices, setChoices] = useState<EditPlanChoices>(() =>
    initialChoices(plan)
  );
  const [busy, setBusy] = useState<"applying" | "replanning" | null>(null);
  const [failure, setFailure] = useState<{
    kind: "stale" | "expired" | "error";
    detail: string;
  } | null>(null);

  const update = (next: Partial<EditPlanChoices>) =>
    setChoices((current) => ({ ...current, ...next }));

  const block = applyBlockOf(planResponse, choices);
  const steps = resolvedSteps(plan, choices);
  const disabled = busy !== null;

  const validation = plan.validation;
  const failedDryRuns = plan.dry_run_results.filter(
    (result) => result.status === "failed"
  );
  const warnings = plan.notes.filter((note) => note.severity === "warning");
  const stillRunningNote = plan.notes.find(
    (note) => note.kind === CHECKS_STILL_RUNNING_NOTE
  );
  const infos = plan.notes.filter(
    (note) => note.severity === "info" && note !== stillRunningNote
  );
  const changedFields = [
    ...plan.field_changes.map((change) => change.field_name),
    ...plan.changed_settings,
  ];

  const apply = async () => {
    setBusy("applying");
    setFailure(null);
    try {
      const outcome = await onApply(buildApplyRequest(planResponse, choices));
      if (outcome.kind !== "applied") setFailure(outcome);
    } finally {
      setBusy(null);
    }
  };

  const replan = async () => {
    setBusy("replanning");
    try {
      await onReplan();
    } finally {
      setBusy(null);
    }
  };

  const reconciliationLabel = (option: ReconciliationOption) => ({
    title: t(`reconciliation.option.${option}.title`),
    description: t(`reconciliation.option.${option}.description`),
  });
  const credentialLabel = (path: CredentialPath) => ({
    title: t(`credential.option.${path}.title`),
    description: t(`credential.option.${path}.description`),
  });

  return (
    <Modal
      open
      onOpenChange={(open) => {
        if (!open && busy === null) onClose();
      }}
    >
      <Modal.Content width="md" height="lg" data-testid="edit-plan-modal">
        <Modal.Header
          icon={SvgCheckSquare}
          title={t("title")}
          description={t("description", {
            count: plan.indexed_document_count,
          })}
          onClose={busy === null ? onClose : undefined}
        />
        <Modal.Body>
          <Section gap={4} alignItems="stretch" height="fit">
            <Text font="main-ui-body" color="text-04">
              {changedFields.length > 0
                ? t("changes.list", { fields: changedFields.join(", ") })
                : t("changes.none")}
            </Text>

            {(failure?.kind === "stale" || failure?.kind === "expired") && (
              <MessageCard
                variant="warning"
                title={t(`${failure.kind}.title`)}
                description={t(`${failure.kind}.description`)}
                bottomChildren={
                  <Button
                    prominence="secondary"
                    icon={busy === "replanning" ? IconLoader : SvgRefreshCw}
                    disabled={disabled}
                    onClick={() => void replan()}
                  >
                    {t("stale.replanButton.label")}
                  </Button>
                }
              />
            )}
            {failure?.kind === "error" && (
              <MessageCard
                variant="error"
                title={t("applyFailed.title")}
                description={failure.detail}
              />
            )}

            {validation !== null ? (
              <ValidationSection
                plan={plan}
                validation={validation}
                blocksApply={planResponse.validation_blocks_apply}
                stillRunningNote={stillRunningNote}
              />
            ) : (
              <Content
                title={t("validation.title")}
                description={t("validation.unchanged")}
                sizePreset="main-ui"
                variant="section"
              />
            )}

            {(warnings.length > 0 || failedDryRuns.length > 0) && (
              <Section gap={2} alignItems="stretch" height="fit">
                <Content
                  title={t("warnings.title")}
                  sizePreset="main-ui"
                  variant="section"
                />
                {warnings.map((note) => (
                  <MessageCard
                    key={note.kind}
                    variant="warning"
                    title={note.message}
                  />
                ))}
                <CheckFailures results={failedDryRuns} variant="warning" />
              </Section>
            )}

            {infos.length > 0 && (
              <Section gap={2} alignItems="stretch" height="fit">
                <Content
                  title={t("notes.title")}
                  sizePreset="main-ui"
                  variant="section"
                />
                {infos.map((note) => (
                  <MessageCard
                    key={note.kind}
                    variant="info"
                    title={note.message}
                  />
                ))}
              </Section>
            )}

            {plan.reconciliation_choice !== null && (
              <Section
                gap={2}
                alignItems="stretch"
                height="fit"
                role="radiogroup"
                aria-label={t("reconciliation.title")}
              >
                <Content
                  title={t("reconciliation.title")}
                  description={t("reconciliation.description", {
                    fields: plan.reconciliation_choice.field_names.join(", "),
                  })}
                  sizePreset="main-ui"
                  variant="section"
                />
                {plan.reconciliation_choice.options.map((option) => (
                  <ChoiceCard
                    key={option}
                    selected={choices.reconciliation === option}
                    disabled={disabled}
                    onSelect={() => update({ reconciliation: option })}
                    {...reconciliationLabel(option)}
                  />
                ))}
              </Section>
            )}

            {plan.credential_choice !== null && (
              <Section
                gap={2}
                alignItems="stretch"
                height="fit"
                role="radiogroup"
                aria-label={t("credential.title")}
              >
                <Content
                  title={t("credential.title")}
                  description={t("credential.description")}
                  sizePreset="main-ui"
                  variant="section"
                />
                {plan.credential_choice.options.map((path) => (
                  <ChoiceCard
                    key={path}
                    selected={
                      (choices.credentialPath ??
                        plan.credential_choice?.default) === path
                    }
                    disabled={disabled}
                    onSelect={() => update({ credentialPath: path })}
                    {...credentialLabel(path)}
                  />
                ))}
              </Section>
            )}

            <Section gap={2} alignItems="stretch" height="fit">
              <Content
                title={t("steps.title")}
                description={
                  steps.length === 0 ? t("steps.none") : t("steps.description")
                }
                sizePreset="main-ui"
                variant="section"
              />
              {steps.map((step) => (
                <StepCard
                  key={step.kind}
                  step={step}
                  disabled={disabled}
                  dropped={choices.droppedSteps.includes(step.kind)}
                  onDroppedChange={(dropped) =>
                    update({
                      droppedSteps: dropped
                        ? [...choices.droppedSteps, step.kind]
                        : choices.droppedSteps.filter(
                            (kind) => kind !== step.kind
                          ),
                    })
                  }
                />
              ))}
            </Section>

            {(canAddStep(plan, choices, "full_reindex") ||
              canAddStep(plan, choices, "prune")) && (
              <Section gap={2} alignItems="stretch" height="fit">
                <Content
                  title={t("extra.title")}
                  description={t("extra.description")}
                  sizePreset="main-ui"
                  variant="section"
                />
                {canAddStep(plan, choices, "full_reindex") && (
                  <ContentAction
                    title={t("extra.fullReindex.title")}
                    description={t("extra.fullReindex.description")}
                    sizePreset="main-ui"
                    variant="section"
                    rightChildren={
                      <InputSwitch
                        checked={choices.addFullReindex}
                        disabled={disabled}
                        aria-label={t("extra.fullReindex.title")}
                        onCheckedChange={(checked) =>
                          update({ addFullReindex: checked })
                        }
                      />
                    }
                  />
                )}
                {canAddStep(plan, choices, "prune") && (
                  <ContentAction
                    title={t("extra.prune.title")}
                    description={t("extra.prune.description")}
                    sizePreset="main-ui"
                    variant="section"
                    rightChildren={
                      <InputSwitch
                        checked={choices.addPrune}
                        disabled={disabled}
                        aria-label={t("extra.prune.title")}
                        onCheckedChange={(checked) =>
                          update({ addPrune: checked })
                        }
                      />
                    }
                  />
                )}
              </Section>
            )}
          </Section>
        </Modal.Body>
        <Modal.Footer>
          <BasicModalFooter
            cancel={
              <Button
                prominence="secondary"
                disabled={disabled}
                onClick={onClose}
              >
                {t("backButton.label")}
              </Button>
            }
            submit={
              <Button
                disabled={
                  disabled ||
                  block !== null ||
                  failure?.kind === "stale" ||
                  failure?.kind === "expired"
                }
                icon={busy === "applying" ? IconLoader : undefined}
                tooltip={block === null ? undefined : t(`blocked.${block}`)}
                onClick={() => void apply()}
              >
                {t("applyButton.label")}
              </Button>
            }
          />
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
