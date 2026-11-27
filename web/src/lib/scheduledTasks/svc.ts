import type {
  ScheduledTaskCreateBody,
  ScheduledTaskPatchBody,
} from "@/app/craft/v1/tasks/types";
import { errorHandlingFetcher, parseErrorDetail } from "@/lib/fetcher";
import type {
  ScheduledRunListResponse,
  ScheduledRunStatus,
  ScheduledRunSummary,
  ScheduledTaskDetail,
} from "@/lib/scheduledTasks/types";

type RequestBody =
  | ScheduledTaskCreateBody
  | ScheduledTaskPatchBody
  | { revisions: Record<string, number> };

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

function scheduledTasksClient(apiBase: string) {
  const tasksUrl = `${apiBase}/scheduled-tasks`;
  const taskUrl = (taskId: string) => `${tasksUrl}/${taskId}`;
  const runsUrl = (taskId: string) => `${taskUrl(taskId)}/runs`;

  async function markScheduledRunsViewed(
    taskId: string,
    runs: readonly Pick<ScheduledRunSummary, "id" | "revision">[]
  ): Promise<ScheduledRunListResponse> {
    const res = await request(`${runsUrl(taskId)}/viewed`, "PATCH", {
      revisions: Object.fromEntries(runs.map((run) => [run.id, run.revision])),
    });
    return res.json();
  }

  return {
    async createScheduledTask(
      body: ScheduledTaskCreateBody
    ): Promise<ScheduledTaskDetail> {
      return (await request(tasksUrl, "POST", body)).json();
    },

    async updateScheduledTask(
      taskId: string,
      body: ScheduledTaskPatchBody
    ): Promise<ScheduledTaskDetail> {
      return (await request(taskUrl(taskId), "PATCH", body)).json();
    },

    async deleteScheduledTask(taskId: string): Promise<void> {
      await request(taskUrl(taskId), "DELETE");
    },

    async runScheduledTaskNow(
      taskId: string
    ): Promise<{ run_id: string; status: ScheduledRunStatus }> {
      return (await request(`${taskUrl(taskId)}/run-now`, "POST")).json();
    },

    listScheduledTaskRuns(
      taskId: string,
      options: { cursor?: string | null; limit: number; unviewed?: boolean }
    ): Promise<ScheduledRunListResponse> {
      const params = new URLSearchParams({ limit: String(options.limit) });
      if (options.cursor) params.set("cursor", options.cursor);
      if (options.unviewed) params.set("unviewed", "true");
      return errorHandlingFetcher<ScheduledRunListResponse>(
        `${runsUrl(taskId)}?${params.toString()}`
      );
    },

    markScheduledRunsViewed,

    async markScheduledRunViewed(
      taskId: string,
      runId: string,
      revision: number
    ): Promise<void> {
      await markScheduledRunsViewed(taskId, [{ id: runId, revision }]);
    },
  };
}

export const {
  createScheduledTask,
  updateScheduledTask,
  deleteScheduledTask,
  runScheduledTaskNow,
  listScheduledTaskRuns,
  markScheduledRunsViewed,
  markScheduledRunViewed,
} = scheduledTasksClient("/api");
