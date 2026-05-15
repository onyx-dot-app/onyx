/**
 * Constants for the Scheduled Tasks UI.
 */

import type { Route } from "next";
import type {
  EditorMode,
  EditorPayload,
} from "@/app/craft/v1/tasks/interfaces";

export const TASKS_PATH = "/craft/v1/tasks" as Route;
export const NEW_TASK_PATH = `${TASKS_PATH}/new` as Route;

export function taskDetailPath(taskId: string): Route {
  return `${TASKS_PATH}/${taskId}` as Route;
}

export function taskEditPath(taskId: string): Route {
  return `${TASKS_PATH}/${taskId}/edit` as Route;
}

export function buildSessionPath(sessionId: string): Route {
  return `/craft/v1?sessionId=${sessionId}` as Route;
}

// Default page size for run history.
export const RUNS_PAGE_SIZE = 50;

// Starter prompts shown on the empty list state. Pulled from the V1 product
// spec — see docs/craft/product/scheduled-tasks.md.
export interface StarterPrompt {
  title: string;
  prompt: string;
  mode: EditorMode;
  payload: EditorPayload;
  timezone?: string; // falls back to user's TZ if absent
}

export const STARTER_PROMPTS: StarterPrompt[] = [
  {
    title: "Hourly Linear board sync",
    prompt:
      "Check if any new work has happened on Craft in the last hour, and if so keep the Craft Linear board up to date.",
    mode: "interval",
    payload: { unit: "hours", every: 1 },
  },
  {
    title: "Monday escalations digest",
    prompt:
      "Summarize last week's customer escalations and post the summary to #cs-leadership.",
    mode: "daily_weekly",
    // 1 = Monday (cron convention: 0=Sun..6=Sat)
    payload: { time_of_day: "09:00", weekdays: [1] },
  },
  {
    title: "Daily 5pm churn-risk report",
    prompt: "Run our churn-risk report and email it to me.",
    mode: "daily_weekly",
    payload: { time_of_day: "17:00", weekdays: [1, 2, 3, 4, 5] },
  },
];
