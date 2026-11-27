import type { ScheduledTaskRunStatus } from "@/app/craft/v1/tasks/types";

export type {
  ScheduledRunListResponse,
  ScheduledRunSummary,
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
