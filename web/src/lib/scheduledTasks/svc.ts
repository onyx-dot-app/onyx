import type {
  ScheduledTaskCreateBody,
  ScheduledTaskPatchBody,
} from "@/app/craft/v1/tasks/types";
import { errorHandlingFetcher, parseErrorDetail } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type {
  ScheduledRunListResponse,
  ScheduledRunStatus,
  ScheduledRunSummary,
  ScheduledTaskDetail,
} from "@/lib/scheduledTasks/types";

type RequestBody =
  | ScheduledTaskCreateBody
  | ScheduledTaskPatchBody
  | { revisions: Record<string, number> }
  | { revision: number };

async function request(
  url: string,
  method: "POST" | "PATCH" | "DELETE",
  body?: RequestBody
): Promise<Response> {
  const res = await fetch(url, {
    method,
    headers:
      body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(
      await parseErrorDetail(res, `Request failed (${res.status})`)
    );
  }
  return res;
}

export async function createScheduledTask(
  body: ScheduledTaskCreateBody
): Promise<ScheduledTaskDetail> {
  const res = await request(SWR_KEYS.chatScheduledTasks, "POST", body);
  return res.json();
}

export async function updateScheduledTask(
  taskId: string,
  body: ScheduledTaskPatchBody
): Promise<ScheduledTaskDetail> {
  const res = await request(SWR_KEYS.chatScheduledTask(taskId), "PATCH", body);
  return res.json();
}

export async function deleteScheduledTask(taskId: string): Promise<void> {
  await request(SWR_KEYS.chatScheduledTask(taskId), "DELETE");
}

export async function runScheduledTaskNow(
  taskId: string
): Promise<{ run_id: string; status: ScheduledRunStatus }> {
  const res = await request(
    `${SWR_KEYS.chatScheduledTask(taskId)}/run-now`,
    "POST"
  );
  return res.json();
}

export async function listScheduledTaskRuns(
  taskId: string,
  options: { cursor?: string | null; limit: number; unviewed?: boolean }
): Promise<ScheduledRunListResponse> {
  const params = new URLSearchParams({ limit: String(options.limit) });
  if (options.cursor) params.set("cursor", options.cursor);
  if (options.unviewed) params.set("unviewed", "true");
  return errorHandlingFetcher<ScheduledRunListResponse>(
    `${SWR_KEYS.chatScheduledTaskRuns(taskId)}?${params.toString()}`
  );
}

export async function markScheduledRunsViewed(
  taskId: string,
  runs: readonly ScheduledRunSummary[]
): Promise<ScheduledRunListResponse> {
  const res = await request(
    `${SWR_KEYS.chatScheduledTaskRuns(taskId)}/viewed`,
    "PATCH",
    {
      revisions: Object.fromEntries(runs.map((run) => [run.id, run.revision])),
    }
  );
  return res.json();
}

export async function markScheduledRunViewed(
  taskId: string,
  runId: string,
  revision: number
): Promise<void> {
  await request(
    `${SWR_KEYS.chatScheduledTaskRuns(taskId)}/${runId}/viewed`,
    "PATCH",
    { revision }
  );
}
