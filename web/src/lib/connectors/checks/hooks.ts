"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import useSWR from "swr";
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
/** Waits this long after the last form edit before a new run starts. */
const FORM_SETTLE_DELAY_MS = 800;

export interface UseDraftCheckRunInput {
  source: ValidSources;
  /** No run starts until a credential is picked. */
  credentialId: number | null;
  accessType: AccessType | null;
  /** The connector config the form would create, keyed by field name. */
  formState: Record<string, unknown>;
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
}

/**
 * The capability checks for an unsaved connector form. Nothing runs until
 * `begin` is called. Then a run starts at once, and again once the credential
 * changes or the form settles after an edit; each run supersedes the last for
 * this form session. Polls while a run is in flight.
 */
export function useDraftCheckRun({
  source,
  credentialId,
  accessType,
  formState,
}: UseDraftCheckRunInput): UseDraftCheckRunResult {
  // One key per form session, so the backend can supersede older runs.
  const [draftKey] = useState<string>(() => crypto.randomUUID());
  const [runId, setRunId] = useState<string | null>(null);
  const [requesting, setRequesting] = useState<boolean>(false);
  const [error, setError] = useState<unknown>(null);
  const [started, setStarted] = useState<boolean>(false);
  // The first run follows the user's click, so it does not wait for the form
  // to settle.
  const firstRun = useRef<boolean>(true);
  // Only the newest start request may set the run id.
  const latestRequest = useRef<number>(0);

  const { data, mutate } = useSWR<DraftCheckRunSnapshot>(
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
      setRequesting(true);
      try {
        const started: DraftCheckRunSnapshot = await startDraftCheckRun({
          source,
          credential_id: credentialId,
          access_type: accessType,
          draft_key: draftKey,
          form_state: formState,
          rerun,
        });
        if (request !== latestRequest.current) return;
        setError(null);
        setRunId(started.run_id);
        // Seed the cache so polling starts from the accepted run.
        await mutate(started, { revalidate: false });
      } catch (startError) {
        if (request === latestRequest.current) setError(startError);
      } finally {
        if (request === latestRequest.current) setRequesting(false);
      }
    },
    [source, credentialId, accessType, draftKey, formState, mutate]
  );

  // Start a run once the credential or the form stops changing. `start` is
  // new on every edit, so the effect reads it through a ref and keys on the
  // serialized form instead.
  const startRef = useRef(start);
  useEffect(() => {
    startRef.current = start;
  }, [start]);
  const formKey: string = JSON.stringify(formState);
  useEffect(() => {
    if (!started || credentialId === null) return;
    const delay: number = firstRun.current ? 0 : FORM_SETTLE_DELAY_MS;
    const timer = setTimeout(() => {
      firstRun.current = false;
      void startRef.current("none");
    }, delay);
    return () => clearTimeout(timer);
  }, [started, credentialId, accessType, formKey, source]);

  // A superseded snapshot belongs to an older run.
  const snapshot: DraftCheckRunSnapshot | null =
    data && data.run_id === runId && data.status !== "superseded" ? data : null;

  return {
    started,
    // Once started, a second start (after a failed request) retries at once.
    begin: () => (started ? void start("none") : setStarted(true)),
    snapshot,
    running: requesting || snapshot?.status === "running",
    error,
    rerun: () => void start("all"),
  };
}
