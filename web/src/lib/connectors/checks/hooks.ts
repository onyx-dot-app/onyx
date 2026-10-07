"use client";

import { useCallback, useEffect, useMemo } from "react";
import useSWR, { useSWRConfig } from "swr";
import { useFormikContext } from "formik";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { startDraftCheckRun } from "@/lib/connectors/checks/svc";
import { connectorFormState } from "@/lib/connectors/checks/formState";
import { SWR_KEYS } from "@/lib/swr-keys";
import { useConnectorConfiguration } from "@/lib/connectors/connectors";
import { splitCredentialBoundFields } from "@/lib/connectors/utils";
import { toWireAccess } from "@/lib/connectors/accessType";
import type {
  CapabilityCheckResult,
  CapabilityCheckStatus,
  ConnectorChecksStatus,
  DraftCheckRunSnapshot,
  DraftCheckState,
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
  /** The credential configuration the latest run started with. */
  ranWith: string | null;
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

// Required checks in these states keep a completed run from passing.
const BLOCKING_STATES: ReadonlySet<string> = new Set([
  "failed",
  "indeterminate",
  "pending",
  "running",
]);

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
  /** True only when `status` is `passed`: the rest of the form may unlock. */
  passed: boolean;
  /** The finished checks of the latest run. */
  results: CapabilityCheckResult[];
  /** Checks queued or running in the latest run. */
  inProgressCount: number;
  /** Checks waiting on a form field before they can run. */
  expectedCount: number;
  /** Starts a run. */
  begin: () => void;
  /** Starts a run that ignores every cached result. */
  rerun: () => void;
}

/**
 * The capability checks for the unsaved add-connector form of `source`. The
 * session lives in the SWR cache, so the checks card, the configuration lock
 * and the Connect button all read the same run by calling this hook. Must be
 * called inside the form's Formik context.
 *
 * Runs start only on request. A completed result counts only for the
 * credential and credential-bound fields it ran with; when they change, the
 * status turns `stale` until the user reruns.
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
      source,
      accessType,
      formState,
      mutate,
    ]
  );

  // A superseded snapshot belongs to an older run.
  const snapshot: DraftCheckRunSnapshot | null =
    run && run.run_id === runId && run.status !== "superseded" ? run : null;
  const checks: DraftCheckState[] = snapshot?.checks ?? [];

  const status: ConnectorChecksStatus = (() => {
    if (credentialId === null || !session) return "notStarted";
    if (session.requesting) return "running";
    if (session.startFailed) return "failedToRun";
    if (!runId) return "notStarted";
    if (!snapshot || snapshot.status === "running") return "running";
    if (snapshot.status === "failed_to_run") return "failedToRun";
    if (session.ranWith !== bindingKey) return "stale";
    return checks.some(
      (check) => check.required && BLOCKING_STATES.has(check.state)
    )
      ? "failed"
      : "passed";
  })();

  return {
    status,
    passed: status === "passed",
    results: checks.flatMap((check) =>
      isFinished(check) ? [toCheckResult(check)] : []
    ),
    // A run that broke will not finish its open checks, so none count.
    inProgressCount:
      status === "failedToRun"
        ? 0
        : checks.filter(
            (check) => check.state === "pending" || check.state === "running"
          ).length,
    expectedCount: checks.filter((check) => check.state === "waiting").length,
    begin: () => void start("none"),
    rerun: () => void start("all"),
  };
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
