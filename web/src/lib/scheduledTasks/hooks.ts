"use client";

import useSWR, { mutate } from "swr";
import type { UnviewedTaskCountResponse } from "@/app/craft/v1/tasks/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";

const UNVIEWED_COUNT_REFRESH_INTERVAL_MS = 30000;

/** Number of the user's scheduled tasks with run results they have not opened. */
export function useUnviewedScheduledTaskCount(enabled: boolean = true): number {
  const { data } = useSWR<UnviewedTaskCountResponse>(
    enabled ? SWR_KEYS.scheduledTasksUnviewedCount : null,
    errorHandlingFetcher,
    {
      refreshInterval: UNVIEWED_COUNT_REFRESH_INTERVAL_MS,
      shouldRetryOnError: false,
    }
  );
  return data?.count ?? 0;
}

/** Refresh every cache that shows viewed state for the runs of `taskId`. */
export async function revalidateScheduledRunViews(taskId: string) {
  const runsKey = SWR_KEYS.scheduledTaskRuns(taskId);
  await Promise.all([
    mutate(SWR_KEYS.scheduledTasksUnviewedCount),
    mutate(SWR_KEYS.scheduledTasks),
    mutate((key) => typeof key === "string" && key.startsWith(runsKey)),
  ]);
}
