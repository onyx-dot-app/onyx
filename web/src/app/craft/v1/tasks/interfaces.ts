/**
 * Shared types for the Scheduled Tasks feature.
 *
 * These mirror the backend Pydantic models defined in
 * ``backend/onyx/server/features/build/scheduled_tasks/api.py``.
 */

export type ScheduledTaskStatus = "ACTIVE" | "PAUSED";

export type ScheduledTaskRunStatus =
  | "QUEUED"
  | "RUNNING"
  | "SUCCEEDED"
  | "FAILED"
  | "SKIPPED"
  | "AWAITING_APPROVAL";

export type ScheduledTaskTriggerSource = "SCHEDULED" | "MANUAL_RUN_NOW";

export type EditorMode = "interval" | "daily_weekly" | "advanced";

export type IntervalUnit = "minutes" | "hours" | "days";

export interface IntervalPayload {
  unit: IntervalUnit;
  every: number;
  time_of_day?: string | null; // "HH:MM" — required when unit=days
}

export interface DailyWeeklyPayload {
  time_of_day: string; // "HH:MM"
  // 0=Sunday .. 6=Saturday (cron convention).
  weekdays: number[];
}

export interface AdvancedPayload {
  cron: string;
}

export type EditorPayload =
  | IntervalPayload
  | DailyWeeklyPayload
  | AdvancedPayload;

export interface ScheduledRunSummary {
  id: string;
  status: ScheduledTaskRunStatus;
  trigger_source: ScheduledTaskTriggerSource;
  started_at: string;
  finished_at: string | null;
  session_id: string | null;
  summary: string | null;
  skip_reason: string | null;
  error_class: string | null;
}

export interface ScheduledTaskListItem {
  id: string;
  name: string;
  human_readable_schedule: string;
  cron_expression: string;
  timezone: string;
  editor_mode: EditorMode;
  status: ScheduledTaskStatus;
  next_run_at: string | null;
  last_run: ScheduledRunSummary | null;
  created_at: string;
  updated_at: string;
}

export interface ScheduledTaskDetail {
  id: string;
  name: string;
  prompt: string;
  human_readable_schedule: string;
  cron_expression: string;
  timezone: string;
  editor_mode: EditorMode;
  status: ScheduledTaskStatus;
  next_run_at: string | null;
  next_runs: string[];
  last_run: ScheduledRunSummary | null;
  created_at: string;
  updated_at: string;
}

export interface ScheduledTaskCreateBody {
  name: string;
  prompt: string;
  editor_mode: EditorMode;
  editor_payload: EditorPayload;
  timezone: string;
  status?: ScheduledTaskStatus;
  run_immediately?: boolean;
}

export interface ScheduledTaskPatchBody {
  name?: string;
  prompt?: string;
  editor_mode?: EditorMode;
  editor_payload?: EditorPayload;
  timezone?: string;
  status?: ScheduledTaskStatus;
}

export interface ScheduledTaskListResponse {
  items: ScheduledTaskListItem[];
}

export interface ScheduledRunListResponse {
  items: ScheduledRunSummary[];
  next_cursor: string | null;
}

export interface RunNowResponse {
  run_id: string;
  status: ScheduledTaskRunStatus;
}

export interface ScheduledRunContextResponse {
  task_id: string;
  task_name: string;
  started_at: string;
}
