"use client";

import { useFormatter, useTranslations } from "next-intl";
import useSWR, { mutate } from "swr";
import type {
  EditorMode,
  UnviewedTaskCountResponse,
} from "@/app/craft/v1/tasks/types";
import { decodeUtcCronToLocalPayload } from "@/app/craft/v1/tasks/schedule";
import type { ScheduledRunContext } from "@/lib/scheduledTasks/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";

const UNVIEWED_COUNT_REFRESH_INTERVAL_MS = 30000;
const RUN_IN_FLIGHT_REFRESH_INTERVAL_MS = 5000;

function useUnviewedCount(key: string | null): number {
  const { data } = useSWR<UnviewedTaskCountResponse>(
    key,
    errorHandlingFetcher,
    {
      refreshInterval: UNVIEWED_COUNT_REFRESH_INTERVAL_MS,
      shouldRetryOnError: false,
    }
  );
  return data?.count ?? 0;
}

/** Number of the user's scheduled tasks with run results they have not opened. */
export function useUnviewedScheduledTaskCount(enabled: boolean = true): number {
  return useUnviewedCount(
    enabled ? SWR_KEYS.scheduledTasksUnviewedCount : null
  );
}

/** As `useUnviewedScheduledTaskCount`, for the tasks that run in chat. */
export function useUnviewedChatScheduledTaskCount(): number {
  return useUnviewedCount(SWR_KEYS.chatScheduledTasksUnviewedCount);
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

/** How often task pages refetch a task, whose runs and next run move in
 * the background. */
export const TASK_REFRESH_INTERVAL_MS = 30_000;

/** As `revalidateScheduledRunViews`, for the tasks that run in chat. */
export async function revalidateChatScheduledRunViews(taskId: string) {
  const runsKey = SWR_KEYS.chatScheduledTaskRuns(taskId);
  await Promise.all([
    mutate(SWR_KEYS.chatScheduledTasksUnviewedCount),
    mutate(SWR_KEYS.chatScheduledTasks),
    mutate(SWR_KEYS.chatScheduledTask(taskId)),
    mutate((key) => typeof key === "string" && key.startsWith(runsKey)),
  ]);
}

/** The scheduled run a chat belongs to; null for a chat that no task
 * created. */
export function useScheduledRunOfChat(chatSessionId: string | null) {
  return useSWR<ScheduledRunContext | null>(
    chatSessionId ? SWR_KEYS.chatScheduledRun(chatSessionId) : null,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      shouldRetryOnError: false,
      refreshInterval: (data) =>
        data?.status === "RUNNING" || data?.status === "AWAITING_APPROVAL"
          ? RUN_IN_FLIGHT_REFRESH_INTERVAL_MS
          : 0,
    }
  );
}

const TIME_RE = /^(\d{1,2}):(\d{2})$/;
// 2024-01-07 is a Sunday, so day `d` of this week is weekday `d` in cron.
const SUNDAY = { year: 2024, month: 0, day: 7 };

/** Formats task schedules and run times in the user's locale and time zone. */
export function useScheduledTaskFormat() {
  const t = useTranslations("scheduledTasks.schedule");
  const format = useFormatter();
  // Schedules decode to browser-local times; next-intl formats in the
  // server's zone unless told otherwise.
  const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;

  function timeOfDay(value: string | null | undefined): string {
    const match = value ? TIME_RE.exec(value) : null;
    if (!match) return "";
    return format.dateTime(
      new Date(2024, 0, 1, Number(match[1]), Number(match[2])),
      { timeStyle: "short", timeZone }
    );
  }

  return {
    /** The schedule in local time. A stored UTC time of day moves with
     * daylight saving, so it is read at the date of `nextRunAt`. */
    schedule(mode: EditorMode, cron: string, nextRunAt: string | null): string {
      const { mode: shown, payload } = decodeUtcCronToLocalPayload(
        mode,
        cron,
        nextRunAt ? new Date(nextRunAt) : new Date()
      );
      if ("cron" in payload) return t("cron", { cron: payload.cron });
      if ("unit" in payload && shown === "interval") {
        if (payload.unit === "days")
          return t("everyDays", {
            count: payload.every,
            time: timeOfDay(payload.time_of_day),
          });
        return payload.unit === "minutes"
          ? t("everyMinutes", { count: payload.every })
          : t("everyHours", { count: payload.every });
      }
      if (!("weekdays" in payload)) return cron;
      const time = timeOfDay(payload.time_of_day);
      const days = Array.from(new Set(payload.weekdays)).sort((a, b) => a - b);
      if (days.length === 0 || days.length === 7) return t("daily", { time });
      return t("weekly", {
        time,
        days: format.list(
          days.map((day) =>
            format.dateTime(
              new Date(SUNDAY.year, SUNDAY.month, SUNDAY.day + day),
              { weekday: "short", timeZone }
            )
          )
        ),
      });
    },
    absolute(iso: string): string {
      return format.dateTime(new Date(iso), {
        dateStyle: "medium",
        timeStyle: "short",
        timeZone,
      });
    },
    relative(iso: string): string {
      return format.relativeTime(new Date(iso), {
        now: new Date(),
        style: "narrow",
      });
    },
  };
}
