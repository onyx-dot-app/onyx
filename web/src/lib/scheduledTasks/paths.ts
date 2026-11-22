export const SCHEDULED_TASKS_PATH = "/app/scheduled-tasks";

export const NEW_SCHEDULED_TASK_PATH = "/app/scheduled-tasks/new";

export type ScheduledTaskPageTab = "runs" | "overview";

export function scheduledTaskHref(
  taskId: string,
  tab?: ScheduledTaskPageTab
): `/app/scheduled-tasks/${string}` {
  return tab && tab !== "runs"
    ? `/app/scheduled-tasks/${taskId}?tab=${tab}`
    : `/app/scheduled-tasks/${taskId}`;
}

export function editScheduledTaskHref(
  taskId: string
): `/app/scheduled-tasks/${string}/edit` {
  return `/app/scheduled-tasks/${taskId}/edit`;
}
