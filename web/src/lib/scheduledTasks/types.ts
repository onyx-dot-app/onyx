import type {
  ScheduledRunSummary as CraftScheduledRunSummary,
  ScheduledTaskRunStatus,
} from "@/app/craft/v1/tasks/types";

export type {
  ScheduledTaskDetail,
  ScheduledTaskListItem,
  ScheduledTaskListResponse,
} from "@/app/craft/v1/tasks/types";

export type ScheduledRunStatus = ScheduledTaskRunStatus;

export interface ScheduledRunContext {
  run_id: string;
  task_id: string;
  task_name: string;
  status: ScheduledRunStatus;
  started_at: string;
  finished_at: string | null;
  revision: number;
  viewed_revision: number | null;
}

export interface ScheduledRunSummary extends CraftScheduledRunSummary {
  /** Why the run failed or stopped, in words the owner can read. */
  error_detail: string | null;
}

export interface ScheduledRunListResponse {
  items: ScheduledRunSummary[];
  next_cursor: string | null;
}
