/**
 * API client for the Scheduled Tasks feature.
 *
 * Always routes through the frontend BFF (``/api/build/...``), per CLAUDE.md.
 * Each function throws on non-2xx, with a human-readable message lifted from
 * the JSON ``detail`` field when present.
 */

import type {
  ScheduledTaskListItem,
  ScheduledTaskDetail,
  ScheduledTaskCreateBody,
  ScheduledTaskPatchBody,
  ScheduledRunListResponse,
  RunNowResponse,
} from "@/app/craft/v1/tasks/interfaces";

const API_BASE = "/api/build/scheduled-tasks";

async function readError(res: Response, fallback: string): Promise<never> {
  let detail: string | undefined;
  try {
    const body = (await res.json()) as { detail?: string };
    detail = body?.detail;
  } catch {
    // ignore parse errors
  }
  throw new Error(detail || `${fallback} (HTTP ${res.status})`);
}

// ---------------------------------------------------------------------------
// Mutations
// ---------------------------------------------------------------------------

// Read paths (list, detail, run history, scheduled-run context) all go
// through `useSWR(SWR_KEYS.*, errorHandlingFetcher)` directly — they don't
// need wrapper helpers here. Pagination on the runs endpoint is still done
// imperatively for "Load more"; see `listScheduledTaskRuns` below.

export async function createScheduledTask(
  body: ScheduledTaskCreateBody
): Promise<ScheduledTaskListItem> {
  const res = await fetch(API_BASE, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) await readError(res, "Failed to create scheduled task");
  return (await res.json()) as ScheduledTaskListItem;
}

export async function updateScheduledTask(
  taskId: string,
  body: ScheduledTaskPatchBody
): Promise<ScheduledTaskDetail> {
  const res = await fetch(`${API_BASE}/${taskId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) await readError(res, "Failed to update scheduled task");
  return (await res.json()) as ScheduledTaskDetail;
}

export async function deleteScheduledTask(taskId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/${taskId}`, { method: "DELETE" });
  if (!res.ok && res.status !== 204) {
    await readError(res, "Failed to delete scheduled task");
  }
}

export async function runScheduledTaskNow(
  taskId: string
): Promise<RunNowResponse> {
  const res = await fetch(`${API_BASE}/${taskId}/run-now`, { method: "POST" });
  if (!res.ok) await readError(res, "Failed to run scheduled task");
  return (await res.json()) as RunNowResponse;
}

// ---------------------------------------------------------------------------
// Runs
// ---------------------------------------------------------------------------

export async function listScheduledTaskRuns(
  taskId: string,
  options?: { cursor?: string | null; limit?: number }
): Promise<ScheduledRunListResponse> {
  const params = new URLSearchParams();
  if (options?.cursor) params.set("cursor", options.cursor);
  if (options?.limit) params.set("limit", String(options.limit));
  const qs = params.toString();
  const url = qs
    ? `${API_BASE}/${taskId}/runs?${qs}`
    : `${API_BASE}/${taskId}/runs`;
  const res = await fetch(url, { method: "GET" });
  if (!res.ok) await readError(res, "Failed to load runs");
  return (await res.json()) as ScheduledRunListResponse;
}
