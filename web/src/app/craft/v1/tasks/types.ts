import type { ExternalAppType } from "@/app/craft/v1/apps/registry";
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
  revision: number;
  viewed_revision: number | null;
}

export interface ScheduledTaskListItem {
  id: string;
  name: string;
  human_readable_schedule: string;
  cron_expression: string;
  editor_mode: EditorMode;
  status: ScheduledTaskStatus;
  next_run_at: string | null;
  last_run: ScheduledRunSummary | null;
  unviewed_run_count: number;
  created_at: string;
  updated_at: string;
}

export interface ScheduledTaskDetail {
  id: string;
  name: string;
  prompt: string;
  human_readable_schedule: string;
  cron_expression: string;
  editor_mode: EditorMode;
  status: ScheduledTaskStatus;
  next_run_at: string | null;
  next_runs: string[];
  last_run: ScheduledRunSummary | null;
  plugins: TaskPluginLink[];
  created_at: string;
  updated_at: string;
}

export interface ScheduledTaskCreateBody {
  name: string;
  prompt: string;
  editor_mode: EditorMode;
  editor_payload: EditorPayload;
  status?: ScheduledTaskStatus;
  run_immediately?: boolean;
  plugins?: TaskPluginLink[];
}

export interface ScheduledTaskPatchBody {
  name?: string;
  prompt?: string;
  editor_mode?: EditorMode;
  editor_payload?: EditorPayload;
  status?: ScheduledTaskStatus;
  plugins?: TaskPluginLink[];
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
  run_id: string;
  task_id: string;
  task_name: string;
  status: ScheduledTaskRunStatus;
  started_at: string;
  finished_at: string | null;
  revision: number;
  viewed_revision: number | null;
}

export interface UnviewedTaskCountResponse {
  count: number;
}

/** The setting of one action on a task; ``inherit`` uses the integration setting. */
export type TaskLinkValue = "inherit" | "allow" | "ask" | "blocked";

/** What a run does when it calls an action. */
export type TaskEffectivePolicy = "allow" | "ask" | "blocked";

export interface TaskActionSettings {
  default: TaskLinkValue;
  actions: Record<string, TaskLinkValue>;
}

/** A plugin the task uses, with its action settings. */
export interface TaskPluginLink {
  plugin_id: string;
  action_settings: TaskActionSettings;
}

export interface TaskActionView {
  key: string;
  display_name: string;
  description: string | null;
  integration_policy: TaskEffectivePolicy;
  /** A task Allow keeps the integration policy. */
  locked: boolean;
}

export interface TaskIntegrationView {
  id: number;
  name: string;
  kind: "mcp" | "api";
  app_type: ExternalAppType | null;
  status: {
    state: "connected" | "not_connected" | "needs_reconnect" | "not_set_up";
    reason: string | null;
  };
  actions: TaskActionView[];
}

/** A plugin a task can use; mirrors ``TaskPluginView`` in the backend. */
export interface TaskPluginView {
  plugin_id: string;
  plugin_name: string;
  enabled: boolean;
  action_settings: TaskActionSettings | null;
  integrations: TaskIntegrationView[];
}
