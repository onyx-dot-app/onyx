"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import useSWR from "swr";
import { Text } from "@opal/components";
import { SvgClock, SvgExternalLink } from "@opal/icons";
import { cn } from "@opal/utils";
import { taskDetailPath } from "@/app/craft/v1/tasks/constants";
import {
  formatAbsolute,
  isScheduledRunContextInFlight,
} from "@/app/craft/v1/tasks/utils";
import type { ScheduledRunContextResponse } from "@/app/craft/v1/tasks/interfaces";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";

interface ScheduledRunBannerProps {
  sessionId: string | null;
  context?: ScheduledRunContextResponse | null;
}

export function useScheduledRunContext(sessionId: string | null) {
  return useSWR<ScheduledRunContextResponse>(
    sessionId ? SWR_KEYS.scheduledRunContext(sessionId) : null,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      refreshInterval: (data) =>
        isScheduledRunContextInFlight(data) ? 5000 : 0,
      shouldRetryOnError: false,
    }
  );
}

/**
 * Header metadata rendered when the active session was created by a scheduled
 * task. When the session is interactive, this returns ``null`` (no DOM is
 * inserted).
 *
 * Uses ``useSWR`` so the per-session lookup is deduped across the chat panel
 * and the parent layout.
 */
export default function ScheduledRunBanner({
  sessionId,
  context,
}: ScheduledRunBannerProps) {
  const t = useTranslations("craft.scheduledRun");
  // 404 is the expected "this session isn't scheduled" signal — the standard
  // fetcher throws on it, which lands in `error` and falls through the
  // `if (!data)` guard below to render nothing. `shouldRetryOnError: false`
  // keeps SWR from hammering the endpoint after a legit 404.
  const { data: fetchedContext } = useScheduledRunContext(
    context === undefined ? sessionId : null
  );
  const data = context === undefined ? fetchedContext : context;

  if (!data) return null;

  const statusText =
    data.status === "RUNNING"
      ? t("status.running")
      : data.status === "AWAITING_APPROVAL"
        ? t("status.awaitingApproval")
        : t("status.startedBy", {
            task: data.task_name,
            time: formatAbsolute(data.started_at),
          });

  return (
    <div
      className="inline-flex min-w-0 max-w-full"
      data-testid="scheduled-run-banner"
    >
      <Link
        href={taskDetailPath(data.task_id)}
        className={cn(
          "group inline-flex min-w-0 max-w-[5.75rem] items-center",
          "overflow-hidden rounded-08 border border-border-01",
          "bg-background-tint-00 px-2 py-1",
          "transition-[max-width,background-color]",
          "duration-[350ms] ease-out",
          "hover:max-w-[30rem] hover:bg-background-tint-01",
          "focus-visible:max-w-[30rem] focus-visible:bg-background-tint-01",
          "focus:outline-hidden focus-visible:ring-2",
          "focus-visible:ring-border-04"
        )}
        data-testid="back-to-task-button"
        title={statusText}
        aria-label={t("viewTask.ariaLabel", {
          task: data.task_name,
          status: statusText,
        })}
      >
        <span className="grid shrink-0 translate-y-px items-center">
          <span
            className={cn(
              "col-start-1 row-start-1 flex h-5 items-center gap-1.5",
              "opacity-100 transition-opacity duration-200 ease-out",
              "group-hover:opacity-0 group-focus-visible:opacity-0"
            )}
          >
            <SvgClock size={14} className="shrink-0 text-text-03" />
            <span className="flex h-5 shrink-0 items-center">
              <Text
                font="figure-small-label"
                color="text-03"
                wordWrap="whitespace-nowrap"
              >
                {t("badge.label")}
              </Text>
            </span>
          </span>
          <span
            className={cn(
              "col-start-1 row-start-1 flex h-5 items-center gap-1.5",
              "opacity-0 transition-opacity duration-200 ease-out",
              "group-hover:opacity-100 group-focus-visible:opacity-100"
            )}
          >
            <SvgExternalLink size={14} className="shrink-0 text-text-03" />
            <span className="flex h-5 shrink-0 items-center">
              <Text
                font="figure-small-label"
                color="text-03"
                wordWrap="whitespace-nowrap"
              >
                {t("viewTask.label")}
              </Text>
            </span>
          </span>
        </span>
        <div
          className={cn(
            "ms-0 flex h-5 w-max max-w-0 translate-y-px items-center",
            "gap-1.5 overflow-hidden opacity-0",
            "transition-[max-width,opacity,margin-inline-start]",
            "duration-[350ms] ease-out",
            "group-hover:ms-1.5 group-hover:max-w-[23rem]",
            "group-hover:opacity-100 group-focus-visible:ms-1.5",
            "group-focus-visible:max-w-[23rem]",
            "group-focus-visible:opacity-100"
          )}
        >
          <div className="h-3 w-px shrink-0 bg-border-01" />
          <span className="flex h-5 min-w-0 -translate-y-px items-center overflow-hidden">
            <Text
              font="main-ui-action"
              color="text-05"
              wordWrap="whitespace-nowrap"
              maxLines={1}
            >
              {data.task_name}
            </Text>
          </span>
          <span className="hidden h-5 shrink-0 items-center xl:flex">
            <Text
              font="secondary-body"
              color="text-03"
              wordWrap="whitespace-nowrap"
            >
              {t("startedAt.label", { time: formatAbsolute(data.started_at) })}
            </Text>
          </span>
        </div>
      </Link>
    </div>
  );
}
