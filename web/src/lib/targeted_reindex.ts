/**
 * Client for the targeted-reindex flow: submit jobs, then poll them until they
 * finish.
 */
import type {
  IndexAttemptError,
  PaginatedIndexAttemptErrors,
  TargetedReindexJobStatus,
  TargetedReindexResponse,
} from "@/lib/connectors/types";

/** Server-enforced cap. Keep in sync with `MAX_TARGETS_PER_REQUEST`
 * in `backend/onyx/db/targeted_reindex.py`. */
export const TARGETED_REINDEX_MAX_PER_REQUEST = 100;

const JOB_POLL_MS = 2000;
// A stalled read is aborted so the loop always reaches its deadline check.
const JOB_READ_TIMEOUT_MS = 10_000;
// Covers time queued in Celery plus the task's 30-minute soft time limit.
const JOB_WAIT_LIMIT_MS = 60 * 60 * 1000;

const TERMINAL_JOB_STATUSES: ReadonlySet<TargetedReindexJobStatus["status"]> =
  new Set(["success", "failed", "completed_with_errors", "canceled"]);

export interface ResolveAllSubmitted {
  job_ids: number[];
  total_error_ids: number;
}

/** Totals over the jobs that ended. `finished` is false when any job failed, was canceled, is missing, or never ended. */
export interface TargetedReindexOutcome {
  finished: boolean;
  resolved: number;
  still_failing: number;
}

export async function fetchAllUnresolvedErrors(
  ccPairId: number,
  indexAttemptId?: number
): Promise<IndexAttemptError[]> {
  const pageSize = 100;
  const collected: IndexAttemptError[] = [];
  let pageNum = 0;

  while (true) {
    const url =
      `/api/manage/admin/cc-pair/${ccPairId}/errors` +
      `?page_num=${pageNum}&page_size=${pageSize}&include_resolved=false` +
      (indexAttemptId === undefined
        ? ""
        : `&index_attempt_id=${indexAttemptId}`);
    const res = await fetch(url);
    if (!res.ok) {
      throw new Error(`Failed to fetch indexing errors (status ${res.status})`);
    }
    const page: PaginatedIndexAttemptErrors = await res.json();
    collected.push(...page.items);

    if (page.items.length < pageSize) break;
    pageNum += 1;
    if (collected.length >= page.total_items) break;
  }

  return collected;
}

function chunk<T>(items: T[], size: number): T[][] {
  if (size <= 0) return [items];
  const out: T[][] = [];
  for (let i = 0; i < items.length; i += size) {
    out.push(items.slice(i, i + size));
  }
  return out;
}

async function submitBatch(
  errorIds: number[]
): Promise<TargetedReindexResponse> {
  const res = await fetch("/api/manage/admin/indexing/targeted-reindex", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ error_ids: errorIds }),
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(
      `targeted-reindex POST failed (status ${res.status}): ${body}`
    );
  }
  return res.json();
}

/** Submits the pair's open errors, or one attempt's, as targeted-reindex jobs. Returns when the POSTs land, not when the jobs finish. */
export async function resolveAllErrorsForCCPair(
  ccPairId: number,
  indexAttemptId?: number
): Promise<ResolveAllSubmitted> {
  const errors = await fetchAllUnresolvedErrors(ccPairId, indexAttemptId);
  return resolveErrors(errors.map((e) => e.id));
}

/** Submits these error ids as targeted-reindex jobs, chunked at the server cap. */
export async function resolveErrors(
  errorIds: number[]
): Promise<ResolveAllSubmitted> {
  if (errorIds.length === 0) {
    return { job_ids: [], total_error_ids: 0 };
  }
  const batches = chunk(errorIds, TARGETED_REINDEX_MAX_PER_REQUEST);
  const responses = await Promise.all(batches.map((b) => submitBatch(b)));
  return {
    job_ids: responses.map((r) => r.targeted_reindex_job_id),
    total_error_ids: errorIds.length,
  };
}

// "missing" is a 404: the job is gone or belongs to another user, so polling cannot recover.
async function fetchJobStatus(
  jobId: number
): Promise<TargetedReindexJobStatus | "missing" | null> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), JOB_READ_TIMEOUT_MS);
  try {
    const res = await fetch(
      `/api/manage/admin/indexing/targeted-reindex/${jobId}`,
      { signal: controller.signal }
    );
    if (res.status === 404) return "missing";
    return res.ok ? await res.json() : null;
  } finally {
    clearTimeout(timer);
  }
}

/** Polls the jobs until each one ends or the wait limit passes. Any other failed read is retried on the next poll. */
export async function waitForTargetedReindexJobs(
  jobIds: number[]
): Promise<TargetedReindexOutcome> {
  const deadline = Date.now() + JOB_WAIT_LIMIT_MS;
  const done = new Map<number, TargetedReindexJobStatus>();
  const missing = new Set<number>();
  while (done.size + missing.size < jobIds.length && Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, JOB_POLL_MS));
    const pending = jobIds.filter((id) => !done.has(id) && !missing.has(id));
    const reads = await Promise.all(
      pending.map(async (id) => ({
        id,
        job: await fetchJobStatus(id).catch(() => null),
      }))
    );
    for (const { id, job } of reads) {
      if (job === "missing") missing.add(id);
      else if (job && TERMINAL_JOB_STATUSES.has(job.status)) done.set(id, job);
    }
  }
  const jobs = Array.from(done.values());
  return {
    finished:
      done.size === jobIds.length &&
      jobs.every((j) => j.status !== "failed" && j.status !== "canceled"),
    resolved: jobs.reduce((sum, j) => sum + j.resolved_count, 0),
    still_failing: jobs.reduce((sum, j) => sum + j.still_failing_count, 0),
  };
}
