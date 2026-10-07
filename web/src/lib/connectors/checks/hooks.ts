"use client";

import { useCallback, useRef, useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import {
  draftCheckRunUrl,
  startDraftCheckRun,
} from "@/lib/connectors/checks/svc";
import type {
  DraftCheckRunSnapshot,
  DraftRerunMode,
} from "@/lib/connectors/checks/types";
import type { ValidSources } from "@/lib/connectors/types/source";
import type { AccessType } from "@/lib/types";

const RUNNING_POLL_INTERVAL_MS = 1500;

export interface UseDraftCheckRunInput {
  source: ValidSources;
  /** No run starts until a credential is picked. */
  credentialId: number | null;
  accessType: AccessType | null;
  /** The connector config the form would create, keyed by field name. */
  formState: Record<string, unknown>;
  /**
   * Identifies the credential configuration: the credential and its bound
   * fields. A result only counts for the configuration it ran with.
   */
  bindingKey: string;
}

export interface UseDraftCheckRunResult {
  /** The user asked for the checks. Nothing runs before that. */
  started: boolean;
  /** Starts the checks, or retries them: the run starts at once. */
  begin: () => void;
  /** The latest run; `null` before the first one starts. */
  snapshot: DraftCheckRunSnapshot | null;
  /** True from a start request until the run leaves `running`. */
  running: boolean;
  /** The last start request failed. */
  error: unknown;
  rerun: () => void;
  /** The credential configuration changed since the last run started. */
  stale: boolean;
  /**
   * The latest run completed for the current credential configuration, and
   * no required check that could run failed, was unverified, or is still
   * pending. Required checks waiting on a form field do not block.
   */
  passed: boolean;
}

// Required checks in these states keep the checks from passing.
const BLOCKING_STATES: ReadonlySet<string> = new Set([
  "failed",
  "indeterminate",
  "pending",
  "running",
]);

/**
 * The capability checks for an unsaved connector form. Runs start only on
 * request, through `begin` or `rerun`; editing the form never schedules one.
 * Each run supersedes the last for this form session. Polls while a run is
 * in flight.
 */
export function useDraftCheckRun({
  source,
  credentialId,
  accessType,
  formState,
  bindingKey,
}: UseDraftCheckRunInput): UseDraftCheckRunResult {
  // One key per form session, so the backend can supersede older runs.
  const [draftKey] = useState<string>(() => crypto.randomUUID());
  const [runId, setRunId] = useState<string | null>(null);
  const [requesting, setRequesting] = useState<boolean>(false);
  const [error, setError] = useState<unknown>(null);
  const [started, setStarted] = useState<boolean>(false);
  // The credential configuration the latest run started with.
  const [ranWith, setRanWith] = useState<string | null>(null);
  // Only the newest start request may set the run id.
  const latestRequest = useRef<number>(0);

  const { mutate } = useSWRConfig();
  const { data } = useSWR<DraftCheckRunSnapshot>(
    runId ? draftCheckRunUrl(runId) : null,
    errorHandlingFetcher,
    {
      refreshInterval: (latest) =>
        latest?.status === "running" ? RUNNING_POLL_INTERVAL_MS : 0,
    }
  );

  const start = useCallback(
    async (rerun: DraftRerunMode) => {
      if (credentialId === null) return;
      const request: number = ++latestRequest.current;
      setStarted(true);
      setRequesting(true);
      setRanWith(bindingKey);
      try {
        const accepted: DraftCheckRunSnapshot = await startDraftCheckRun({
          source,
          credential_id: credentialId,
          access_type: accessType,
          draft_key: draftKey,
          form_state: formState,
          rerun,
        });
        if (request !== latestRequest.current) return;
        setError(null);
        // Seed the new run's cache entry first, so the card shows the
        // accepted run at once and polling starts from it.
        await mutate(draftCheckRunUrl(accepted.run_id), accepted, {
          revalidate: false,
        });
        setRunId(accepted.run_id);
      } catch (startError) {
        if (request === latestRequest.current) setError(startError);
      } finally {
        if (request === latestRequest.current) setRequesting(false);
      }
    },
    [source, credentialId, accessType, draftKey, formState, bindingKey, mutate]
  );

  // A superseded snapshot belongs to an older run.
  const snapshot: DraftCheckRunSnapshot | null =
    data && data.run_id === runId && data.status !== "superseded" ? data : null;
  const stale: boolean = ranWith !== null && ranWith !== bindingKey;
  const passed: boolean =
    !stale &&
    snapshot?.status === "completed" &&
    !snapshot.checks.some(
      (check) => check.required && BLOCKING_STATES.has(check.state)
    );

  return {
    started,
    begin: () => void start("none"),
    snapshot,
    running: requesting || snapshot?.status === "running",
    error,
    rerun: () => void start("all"),
    stale,
    passed,
  };
}
