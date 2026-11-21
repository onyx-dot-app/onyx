import type {
  EditorMode,
  ScheduledRunSummary as CraftRunSummary,
  ScheduledTaskRunStatus as CraftRunStatus,
  ScheduledTaskStatus,
  TaskIntegrationLink,
} from "@/app/craft/v1/tasks/types";

export type ScheduledRunStatus = CraftRunStatus | "CANCELLED";

/** A run of a task. A run from Craft has no `chat_session_id`, so it
 * cannot open in chat. */
export interface ScheduledRunSummary extends Omit<CraftRunSummary, "status"> {
  status: ScheduledRunStatus;
}

export interface ScheduledTaskListItem {
  id: string;
  name: string;
  cron_expression: string;
  editor_mode: EditorMode;
  status: ScheduledTaskStatus;
  next_run_at: string | null;
  last_run: ScheduledRunSummary | null;
  unviewed_run_count: number;
}

export interface ScheduledTaskDetail extends ScheduledTaskListItem {
  prompt: string;
  next_runs: string[];
  integrations: TaskIntegrationLink[];
}

export interface ScheduledTaskListResponse {
  items: ScheduledTaskListItem[];
}

export interface ScheduledRunListResponse {
  items: ScheduledRunSummary[];
  next_cursor: string | null;
}

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
