/**
 * Client for the targeted-reindex flow.
 *
 * Fire-and-forget: the modal kicks reindex jobs off and SWR auto-refresh
 * on the errors endpoint reflects per-row resolution as the backend
 * task lands docs. No client-side polling of job status.
 */
import {
  IndexAttemptError,
  PaginatedIndexAttemptErrors,
  TargetedReindexResponse,
} from "@/app/admin/connector/[ccPairId]/types";

/** Server-enforced cap. Keep in sync with `MAX_TARGETS_PER_REQUEST`
 * in `backend/onyx/db/targeted_reindex.py`. */
export const TARGETED_REINDEX_MAX_PER_REQUEST = 100;

export interface ResolveAllSubmitted {
  job_ids: number[];
  total_error_ids: number;
}

export async function fetchAllUnresolvedErrors(
  ccPairId: number
): Promise<IndexAttemptError[]> {
  const pageSize = 100;
  const collected: IndexAttemptError[] = [];
  let pageNum = 0;

  while (true) {
    const url =
      `/api/manage/admin/cc-pair/${ccPairId}/errors` +
      `?page_num=${pageNum}&page_size=${pageSize}&include_resolved=false`;
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

/**
 * Submit every unresolved error_id for a cc_pair as one or more
 * targeted-reindex jobs (chunked at MAX_TARGETS_PER_REQUEST). Returns
 * once the POSTs complete; does NOT wait for the celery jobs to finish.
 * The errors-list table self-refreshes via SWR and rows flip to
 * Resolved as the backend marks them.
 */
export async function resolveAllErrorsForCCPair(
  ccPairId: number
): Promise<ResolveAllSubmitted> {
  const errors = await fetchAllUnresolvedErrors(ccPairId);
  if (errors.length === 0) {
    return { job_ids: [], total_error_ids: 0 };
  }

  const errorIds = errors.map((e) => e.id);
  const batches = chunk(errorIds, TARGETED_REINDEX_MAX_PER_REQUEST);

  const responses = await Promise.all(batches.map((b) => submitBatch(b)));
  return {
    job_ids: responses.map((r) => r.targeted_reindex_job_id),
    total_error_ids: errorIds.length,
  };
}
