"use client";

import { createElement, useCallback, useEffect, useMemo, useRef } from "react";
import { useTranslations } from "next-intl";
import { SvgProgressRing } from "@opal/icons";
import { IconLoader } from "@opal/loaders";
import type { IconFunctionComponent, IconProps } from "@opal/types";
import useSWR, { type SWRResponse, useSWRConfig } from "swr";
import { useFormikContext } from "formik";
import { errorHandlingFetcher } from "@/lib/fetcher";
import {
  fetchDraftCheckPlan,
  startDraftCheckRun,
} from "@/lib/connectors/checks/svc";
import { INDETERMINATE_CHECKS_BLOCK } from "@/lib/connectors/checks/constants";
import { connectorFormState } from "@/lib/connectors/checks/formState";
import { SWR_KEYS } from "@/lib/swr-keys";
import { useConnectorConfiguration } from "@/lib/connectors/connectors";
import { splitCredentialBoundFields } from "@/lib/connectors/utils";
import { toWireAccess } from "@/lib/connectors/accessType";
import { checksProgress } from "@/lib/connectors/checks/progress";
import type {
  CapabilityCheckResult,
  CapabilityCheckStatus,
  ConnectorChecksStatus,
  DraftCheckPlan,
  DraftCheckRunSnapshot,
  DraftCheckState,
  DraftCheckStateKind,
  DraftRerunMode,
} from "@/lib/connectors/checks/types";
import type { ConfigurableSources } from "@/lib/connectors/types/source";
import type { AccessType } from "@/lib/types";

const RUNNING_POLL_INTERVAL_MS = 1500;

/**
 * One add-connector form's check session, kept in the SWR cache so every
 * component that calls `useConnectorChecks` for the source shares it.
 */
interface ConnectorChecksSession {
  /** Identifies the form session to the backend, which supersedes its runs. */
  draftKey: string;
  /** The latest run. */
  runId: string | null;
  /** The credential and bound fields the latest run started with. */
  ranWith: string | null;
  /** The access type and form values the latest run started with. */
  ranWithForm: string | null;
  /** A start request is in flight. */
  requesting: boolean;
  /** The last start request failed. */
  startFailed: boolean;
  /** Increments per start, so only the newest request applies its result. */
  request: number;
}

const FINISHED_STATES: ReadonlySet<string> = new Set<CapabilityCheckStatus>([
  "passed",
  "failed",
  "indeterminate",
  "skipped",
]);

/** A required check in this state keeps Create, or the form, locked. */
function blocks(check: DraftCheckState): boolean {
  switch (check.state) {
    case "passed":
    case "skipped":
    case "not_applicable":
      return false;
    case "indeterminate":
      return INDETERMINATE_CHECKS_BLOCK;
    case "failed":
    case "pending":
    case "running":
    case "waiting":
      return true;
  }
}

/** A check is the same across a plan and a run by its capability and ID. */
function checkKey(check: DraftCheckState): string {
  return `${check.capability}:${check.check_id}`;
}

function isFinished(
  check: DraftCheckState
): check is DraftCheckState & { state: CapabilityCheckStatus } {
  return FINISHED_STATES.has(check.state);
}

function toCheckResult(
  check: DraftCheckState & { state: CapabilityCheckStatus }
): CapabilityCheckResult {
  return {
    capability: check.capability,
    check_id: check.check_id,
    display_name: check.display_name,
    required: check.required,
    status: check.state,
    message: check.message,
    remediation: check.remediation,
    docs_link: check.docs_link,
    duration_ms: check.duration_ms,
  };
}

const NO_CHECKS: Record<DraftCheckStateKind, number> = {
  pending: 0,
  running: 0,
  passed: 0,
  failed: 0,
  indeterminate: 0,
  skipped: 0,
  waiting: 0,
  not_applicable: 0,
};

function countStates(
  checks: DraftCheckState[],
  broken: boolean
): Record<DraftCheckStateKind, number> {
  const counts = { ...NO_CHECKS };
  for (const check of checks) counts[check.state] += 1;
  // A run that broke will not finish its open checks.
  if (broken) {
    counts.pending = 0;
    counts.running = 0;
  }
  return counts;
}

function formAccessType(values: Record<string, unknown>): AccessType {
  const formValue: unknown = values.access_type;
  const accessType: AccessType =
    formValue === "private" || formValue === "sync" ? formValue : "public";
  return toWireAccess(accessType, {
    restrict_access_to_groups: values.restrict_access_to_groups === true,
    restriction_group_ids: Array.isArray(values.restriction_group_ids)
      ? values.restriction_group_ids.filter(
          (id): id is number => typeof id === "number"
        )
      : [],
  }).access_type;
}

export interface UseConnectorChecksInput {
  source: ConfigurableSources;
  /** The credential the checks run with; `null` until one is usable. */
  credentialId: number | null;
}

export interface UseConnectorChecksResult {
  status: ConnectorChecksStatus;
  /**
   * The checks a run would hold for this form, before any run; `undefined`
   * while they load.
   */
  plan: DraftCheckPlan | undefined;
  /**
   * The rest of the form may unlock: every check that validates the
   * credential with its bound fields has passed. True at once when the source
   * has none.
   */
  formUnlocked: boolean;
  /**
   * Create may run: the form is unlocked, and no required check is failed or
   * still to run in a run of the current form. True without a run when no
   * required check applies.
   */
  createReady: boolean;
  /** The form changed since checks started; a new run would cover it. */
  needsRun: boolean;
  /** Identifies the current form: what a new run would check. */
  formKey: string;
  /** The finished checks of the latest run. */
  results: CapabilityCheckResult[];
  /** The latest run's checks still to finish: running, queued or waiting. */
  openChecks: DraftCheckState[];
  /** Checks queued or running in the latest run. */
  inProgressCount: number;
  /** Checks waiting on a form field before they can run. */
  expectedCount: number;
  /** The latest run's checks, counted per state. */
  stateCounts: Record<DraftCheckStateKind, number>;
  /** Starts a run. */
  begin: () => void;
  /** Starts a run that ignores every cached result. */
  rerun: () => void;
  /** Starts a run for the current form, reusing cached results. */
  refresh: () => void;
}

/**
 * The capability checks for the unsaved add-connector form of `source`. The
 * session lives in the SWR cache, so the checks card, the configuration lock
 * and the Connect button all read the same run by calling this hook. Must be
 * called inside the form's Formik context.
 *
 * The first run starts on request. A change to the credential or its bound
 * fields resets the checks to that request. Any other form change leaves the
 * result out of date for Create until a new run (see `refresh`) covers it.
 */
export function useConnectorChecks({
  source,
  credentialId,
}: UseConnectorChecksInput): UseConnectorChecksResult {
  const { values } = useFormikContext<Record<string, unknown>>();
  const configuration = useConnectorConfiguration(source);
  const { mutate } = useSWRConfig();
  const sessionKey = SWR_KEYS.connectorCheckSession(source);
  const { data: session } = useSWR<ConnectorChecksSession>(sessionKey, null);

  const formState: Record<string, unknown> = useMemo(
    () => connectorFormState(configuration, values),
    [configuration, values]
  );
  // The credential and its bound fields: what a result is valid for.
  const bindingKey: string = useMemo(() => {
    const bound = splitCredentialBoundFields(source, configuration);
    const boundValues: unknown[] = [...bound.values, ...bound.advancedValues]
      .map((field) => field.name)
      .sort()
      .map((name) => values[name]);
    return JSON.stringify([credentialId, boundValues]);
  }, [source, configuration, values, credentialId]);
  const accessType: AccessType = formAccessType(values);
  // The whole form a run checks: what Create's result is valid for.
  const formKey: string = useMemo(
    () => JSON.stringify([accessType, formState]),
    [accessType, formState]
  );
  const { data: plan } = useConnectorCheckPlan(source, accessType);

  const runId: string | null = session?.runId ?? null;
  const { data: run } = useSWR<DraftCheckRunSnapshot>(
    runId ? SWR_KEYS.connectorCheckRun(runId) : null,
    errorHandlingFetcher,
    {
      refreshInterval: (latest) =>
        latest?.status === "running" ? RUNNING_POLL_INTERVAL_MS : 0,
    }
  );

  const start = useCallback(
    async (rerun: DraftRerunMode) => {
      if (credentialId === null) return;
      const draftKey: string = session?.draftKey ?? crypto.randomUUID();
      const request: number = (session?.request ?? 0) + 1;
      await mutate<ConnectorChecksSession>(
        sessionKey,
        {
          draftKey,
          runId: session?.runId ?? null,
          ranWith: bindingKey,
          ranWithForm: formKey,
          requesting: true,
          startFailed: false,
          request,
        },
        { revalidate: false }
      );
      // Only the newest start request may write its outcome.
      const settle = (
        update: (current: ConnectorChecksSession) => ConnectorChecksSession
      ) =>
        mutate<ConnectorChecksSession>(
          sessionKey,
          (current) =>
            current && current.request === request ? update(current) : current,
          { revalidate: false }
        );
      try {
        const accepted: DraftCheckRunSnapshot = await startDraftCheckRun({
          source,
          credential_id: credentialId,
          access_type: accessType,
          draft_key: draftKey,
          form_state: formState,
          rerun,
        });
        // Seed the run first, so readers show it at once and poll from it.
        await mutate(SWR_KEYS.connectorCheckRun(accepted.run_id), accepted, {
          revalidate: false,
        });
        await settle((current) => ({
          ...current,
          runId: accepted.run_id,
          requesting: false,
        }));
      } catch {
        await settle((current) => ({
          ...current,
          requesting: false,
          startFailed: true,
        }));
      }
    },
    [
      credentialId,
      session,
      sessionKey,
      bindingKey,
      formKey,
      source,
      accessType,
      formState,
      mutate,
    ]
  );

  // Results count only for the credential and bound fields they ran with.
  const current: boolean = !!session && session.ranWith === bindingKey;
  // A superseded snapshot belongs to an older run.
  const snapshot: DraftCheckRunSnapshot | null =
    current && run && run.run_id === runId && run.status !== "superseded"
      ? run
      : null;
  const checks: DraftCheckState[] = snapshot?.checks ?? [];

  const status: ConnectorChecksStatus = (() => {
    if (credentialId === null || !session || !current) return "notStarted";
    if (session.requesting) return "running";
    if (session.startFailed) return "failedToRun";
    if (!runId) return "notStarted";
    if (!snapshot || snapshot.status === "running") return "running";
    if (snapshot.status === "failed_to_run") return "failedToRun";
    return checks.some(
      (check) => check.required && check.state !== "waiting" && blocks(check)
    )
      ? "failed"
      : "passed";
  })();

  const applicable: DraftCheckState[] = (plan?.checks ?? []).filter(
    (check) => check.state !== "not_applicable"
  );
  const runStates: Map<string, DraftCheckState> = new Map(
    checks.map((check) => [checkKey(check), check])
  );
  const bindingChecks = applicable.filter((check) => check.validates_binding);
  const formUnlocked: boolean =
    plan !== undefined &&
    bindingChecks.every((check) => {
      const result = runStates.get(checkKey(check));
      return result !== undefined && !blocks(result);
    });
  const ranThisForm: boolean =
    !!session &&
    !session.requesting &&
    session.ranWithForm === formKey &&
    snapshot?.status === "completed";
  const createReady: boolean =
    formUnlocked &&
    (!applicable.some((check) => check.required) ||
      (ranThisForm &&
        !checks.some((check) => check.required && blocks(check))));

  return {
    status,
    plan,
    formUnlocked,
    createReady,
    formKey,
    needsRun:
      !!session &&
      current &&
      runId !== null &&
      !session.requesting &&
      session.ranWithForm !== formKey,
    results: checks.flatMap((check) =>
      isFinished(check) ? [toCheckResult(check)] : []
    ),
    // A run that broke will not finish its queued or running checks.
    openChecks: checks.filter((check) =>
      check.state === "waiting"
        ? true
        : (check.state === "pending" || check.state === "running") &&
          status !== "failedToRun"
    ),
    // A run that broke will not finish its open checks, so none count.
    inProgressCount:
      status === "failedToRun"
        ? 0
        : checks.filter(
            (check) => check.state === "pending" || check.state === "running"
          ).length,
    expectedCount: checks.filter((check) => check.state === "waiting").length,
    stateCounts: countStates(checks, status === "failedToRun"),
    begin: () => void start("none"),
    rerun: () => void start("all"),
    refresh: () => void start("none"),
  };
}

/**
 * The checks a run would hold for `source` with this access type, fetched
 * once per pair. Which checks exist and which are required does not depend
 * on the credential.
 */
export function useConnectorCheckPlan(
  source: ConfigurableSources,
  accessType: AccessType
): SWRResponse<DraftCheckPlan> {
  return useSWR<DraftCheckPlan>(
    SWR_KEYS.connectorCheckPlan(source, accessType),
    () =>
      fetchDraftCheckPlan({
        source,
        access_type: accessType,
        form_state: {},
      }),
    { revalidateOnFocus: false }
  );
}

/**
 * Clears the check session of `source` when the add-connector page mounts,
 * so a return visit does not show the previous visit's run.
 */
export function useResetConnectorChecks(source: ConfigurableSources): void {
  const { mutate } = useSWRConfig();
  useEffect(() => {
    void mutate(SWR_KEYS.connectorCheckSession(source), undefined, {
      revalidate: false,
    });
  }, [source, mutate]);
}

export interface ConnectorChecksProgress {
  /** The header icon: the ring, or the spinner before anything starts. */
  icon: IconFunctionComponent;
  /** The `(complete/counted)` title suffix; absent with nothing to count. */
  suffix: string | undefined;
}

/**
 * The checks' header icon and count, both from `checksProgress`, ready for a
 * `Content` icon slot and suffix.
 */
export function useConnectorChecksProgress(
  counts: Record<DraftCheckStateKind, number>,
  status: ConnectorChecksStatus
): ConnectorChecksProgress {
  const t = useTranslations("admin.connectorChecks");
  const { ring, complete, counted } = checksProgress(counts, status);
  const success = ring?.success;
  const error = ring?.error;
  const warning = ring?.warning;
  const neutral = ring?.neutral;
  const rest = ring?.rest;
  const showRing: boolean = ring !== null;
  const icon = useMemo<IconFunctionComponent>(
    () =>
      showRing
        ? function ChecksRingIcon(props: IconProps) {
            return createElement(SvgProgressRing, {
              ...props,
              success,
              error,
              warning,
              neutral,
              rest,
            });
          }
        : IconLoader,
    [showRing, success, error, warning, neutral, rest]
  );
  return {
    icon,
    suffix:
      counted > 0 ? t("titleCount", { complete, total: counted }) : undefined,
  };
}

function isTyping(): boolean {
  const focused = document.activeElement;
  return (
    focused instanceof HTMLInputElement ||
    focused instanceof HTMLTextAreaElement ||
    (focused instanceof HTMLElement && focused.isContentEditable)
  );
}

/**
 * Keeps the checks current as the form fills in: once checks have started, a
 * form change starts a run when the user leaves the field, or at once when no
 * text field has focus (a toggle or a select). Waiting checks run as their
 * fields are set; cached results keep unchanged checks from running again.
 *
 * Call it from one component only, so one change starts one run.
 */
export function useConnectorChecksAutoRun({
  needsRun,
  formKey,
  refresh,
}: Pick<UseConnectorChecksResult, "needsRun" | "formKey" | "refresh">): void {
  const startedFor = useRef<string | null>(null);
  useEffect(() => {
    if (!needsRun) return;
    const run = () => {
      if (startedFor.current === formKey) return;
      startedFor.current = formKey;
      refresh();
    };
    if (!isTyping()) {
      run();
      return;
    }
    document.addEventListener("focusout", run, { once: true });
    return () => document.removeEventListener("focusout", run);
  }, [needsRun, formKey, refresh]);
}
