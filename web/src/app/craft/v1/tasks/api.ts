import { craftScheduledTasksClient } from "@/lib/scheduledTasks/svc";

export const {
  createScheduledTask,
  updateScheduledTask,
  deleteScheduledTask,
  runScheduledTaskNow,
  listScheduledTaskRuns,
  markScheduledRunsViewed,
} = craftScheduledTasksClient;
