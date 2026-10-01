"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import {
  capabilityReportUrl,
  getDraftCheckRun,
  runCapabilityCheck,
  startDraftCheckRun,
} from "@/lib/connectors/checks/svc";
import {
  isDraftRunSettled,
  requiredChecksStatus,
} from "@/lib/connectors/checks/draft";
import type {
  CapabilityReportSnapshot,
  DraftCheckRunRequest,
  DraftCheckRunSnapshot,
  RequiredChecksStatus,
} from "@/lib/connectors/checks/types";
import type { AccessType, ValidSources } from "@/lib/types";

const RUNNING_POLL_INTERVAL_MS = 2000;

export interface UseCapabilityReportResult {
  /** `null` when no run has ever been stored for this scope. */
  snapshot: CapabilityReportSnapshot | null | undefined;
  isLoading: boolean;
  error: unknown;
  /** True from the re-run request until the row reads `completed`. */
  running: boolean;
  rerun: () => Promise<void>;
}

/**
 * The latest capability report for a credential, scoped to a connector when
 * given. Polls while a run is in flight so the card settles on its own.
 */
export function useCapabilityReport(
  credentialId: number,
  connectorId?: number | null
): UseCapabilityReportResult {
  const [requesting, setRequesting] = useState(false);
  const { data, error, isLoading, mutate } =
    useSWR<CapabilityReportSnapshot | null>(
      capabilityReportUrl(credentialId, connectorId),
      errorHandlingFetcher,
      {
        refreshInterval: (latest) =>
          latest?.run_status === "running" ? RUNNING_POLL_INTERVAL_MS : 0,
      }
    );

  const rerun = useCallback(async () => {
    setRequesting(true);
    try {
      const accepted = await runCapabilityCheck(credentialId, connectorId);
      // Seed the running row so polling starts before the next fetch.
      await mutate(accepted, { revalidate: false });
    } finally {
      setRequesting(false);
    }
  }, [credentialId, connectorId, mutate]);

  return {
    snapshot: data,
    isLoading,
    error,
    running: requesting || data?.run_status === "running",
    rerun,
  };
}

const DRAFT_POLL_INTERVAL_MS = 1000;

export interface DraftCheckRunInput {
  /** The `connector_specific_config` the create request would send. */
  formState: Record<string, unknown>;
  /** The wire access type the create request would send. */
  accessType: AccessType;
}

export interface DraftCheckRunOptions {
  /** Start a new run even when the last run had the same input. */
  force?: boolean;
}

/**
 * How a `run` call ended:
 * - `settled`: the run finished, was superseded, or could not run.
 * - `stale`: a newer `run` call, or a credential change, replaced it.
 * - `error`: the request failed.
 */
export type DraftCheckRunOutcome =
  | { kind: "settled"; snapshot: DraftCheckRunSnapshot }
  | { kind: "stale" }
  | { kind: "error"; error: unknown };

export interface UseDraftConnectorChecksResult {
  /** The latest snapshot of the latest run; `null` before the first run. */
  snapshot: DraftCheckRunSnapshot | null;
  /** True from a `run` call until its run settles. */
  running: boolean;
  error: unknown;
  requiredStatus: RequiredChecksStatus;
  /**
   * Runs the checks for the input and resolves when the run settles. An
   * input equal to the last run's joins that run instead of starting another.
   */
  run: (
    input: DraftCheckRunInput,
    options?: DraftCheckRunOptions
  ) => Promise<DraftCheckRunOutcome>;
  /** The settled snapshot of the last run when its input equals `input`. */
  settledSnapshotFor: (
    input: DraftCheckRunInput
  ) => DraftCheckRunSnapshot | null;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Capability checks on an unsaved connector form. One draft key per mounted
 * form, so a newer run supersedes the older one on the server. A credential
 * change drops the previous results.
 */
export function useDraftConnectorChecks(
  source: ValidSources,
  credentialId: number | null
): UseDraftConnectorChecksResult {
  const [draftKey] = useState(() => crypto.randomUUID());
  const [snapshot, setSnapshot] = useState<DraftCheckRunSnapshot | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<unknown>(null);

  // Bumped by every run and credential change; a response from an older
  // generation is ignored.
  const generationRef = useRef(0);
  const lastRunRef = useRef<{
    key: string;
    promise: Promise<DraftCheckRunOutcome>;
    settled: DraftCheckRunSnapshot | null;
  } | null>(null);

  useEffect(() => {
    generationRef.current += 1;
    lastRunRef.current = null;
    setSnapshot(null);
    setRunning(false);
    setError(null);
  }, [credentialId]);

  useEffect(
    () => () => {
      generationRef.current += 1;
    },
    []
  );

  const buildRequest = useCallback(
    (input: DraftCheckRunInput): DraftCheckRunRequest | null =>
      credentialId === null
        ? null
        : {
            source,
            credential_id: credentialId,
            access_type: input.accessType,
            draft_key: draftKey,
            form_state: input.formState,
          },
    [source, credentialId, draftKey]
  );

  const run = useCallback(
    (
      input: DraftCheckRunInput,
      options: DraftCheckRunOptions = {}
    ): Promise<DraftCheckRunOutcome> => {
      const request = buildRequest(input);
      if (request === null) return Promise.resolve({ kind: "stale" });
      const key = JSON.stringify(request);
      const last = lastRunRef.current;
      if (!options.force && last !== null && last.key === key) {
        return last.promise;
      }

      const generation = ++generationRef.current;
      const isCurrent = () => generation === generationRef.current;
      setRunning(true);
      setError(null);

      const promise = (async (): Promise<DraftCheckRunOutcome> => {
        try {
          let latest = await startDraftCheckRun(request);
          while (true) {
            if (!isCurrent()) return { kind: "stale" };
            setSnapshot(latest);
            if (isDraftRunSettled(latest)) break;
            await sleep(DRAFT_POLL_INTERVAL_MS);
            if (!isCurrent()) return { kind: "stale" };
            latest = await getDraftCheckRun(latest.run_id);
          }
          const entry = lastRunRef.current;
          if (entry !== null && entry.key === key) entry.settled = latest;
          return { kind: "settled", snapshot: latest };
        } catch (caught) {
          if (!isCurrent()) return { kind: "stale" };
          // A failed request must not satisfy the next identical run.
          lastRunRef.current = null;
          setError(caught);
          return { kind: "error", error: caught };
        } finally {
          if (isCurrent()) setRunning(false);
        }
      })();
      lastRunRef.current = { key, promise, settled: null };
      return promise;
    },
    [buildRequest]
  );

  const settledSnapshotFor = useCallback(
    (input: DraftCheckRunInput): DraftCheckRunSnapshot | null => {
      const request = buildRequest(input);
      const last = lastRunRef.current;
      if (request === null || last === null) return null;
      return last.key === JSON.stringify(request) ? last.settled : null;
    },
    [buildRequest]
  );

  return {
    snapshot,
    running,
    error,
    requiredStatus: requiredChecksStatus(snapshot),
    run,
    settledSnapshotFor,
  };
}
