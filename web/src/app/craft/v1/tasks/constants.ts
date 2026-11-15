/**
 * Constants for the Scheduled Tasks UI.
 */

import type { Route } from "next";

export const TASKS_PATH = "/craft/v1/tasks" satisfies Route;
export const NEW_TASK_PATH = `${TASKS_PATH}/new` satisfies Route;

export function taskDetailPath(taskId: string): Route {
  // SAFETY: the `/craft/v1/tasks/[id]` route.
  return `${TASKS_PATH}/${taskId}` as Route;
}

export function taskEditPath(taskId: string): Route {
  // SAFETY: the `/craft/v1/tasks/[id]/edit` route.
  return `${TASKS_PATH}/${taskId}/edit` as Route;
}

export function buildSessionPath(sessionId: string): Route {
  return `/craft/v1?sessionId=${sessionId}`;
}

// Default page size for the scheduled task list.
export const TASKS_PAGE_SIZE = 20;

// Default page size for run history.
export const RUNS_PAGE_SIZE = 50;

// Largest run-history page the API returns.
export const RUNS_MAX_PAGE_SIZE = 100;
