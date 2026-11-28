import type { ExternalAppType } from "@/app/craft/v1/apps/registry";
import type {
  ConnectionState,
  IntegrationKind,
  LinkValue,
  PolicyValue,
} from "@/lib/integrations/types";
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
  | "AWAITING_APPROVAL"
  | "CANCELLED";

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
  chat_session_id: string | null;
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
  integrations: TaskIntegrationLink[];
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
  integrations?: TaskIntegrationLink[];
}

export interface ScheduledTaskPatchBody {
  name?: string;
  prompt?: string;
  editor_mode?: EditorMode;
  editor_payload?: EditorPayload;
  status?: ScheduledTaskStatus;
  integrations?: TaskIntegrationLink[];
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

export interface UnviewedTaskCountResponse {
  count: number;
}

export interface TaskActionSettings {
  default: LinkValue;
  actions: Record<string, LinkValue>;
}

/** An integration the task uses, with its action settings. */
export interface TaskIntegrationLink {
  integration_id: number;
  action_settings: TaskActionSettings;
}

export interface TaskActionView {
  key: string;
  display_name: string;
  description: string | null;
  integration_policy: PolicyValue;
  /** A task Allow keeps the integration policy. */
  locked: boolean;
}

/** An integration a task can use; mirrors ``TaskIntegrationView`` in the
 * backend. */
export interface TaskIntegrationView {
  id: number;
  name: string;
  kind: IntegrationKind;
  app_type: ExternalAppType | null;
  status: {
    state: ConnectionState;
    reason: string | null;
  };
  actions: TaskActionView[];
  /** The task uses the integration. */
  enabled: boolean;
  /** The stored settings of the task; null when not enabled. */
  action_settings: TaskActionSettings | null;
  /** False: a run does not use the integration now. The task keeps its
   * settings. */
  runnable: boolean;
}
