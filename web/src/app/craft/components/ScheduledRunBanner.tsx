"use client";

import useSWR from "swr";
import Text from "@/refresh-components/texts/Text";
import { Button } from "@opal/components";
import { SvgArrowLeft, SvgClock } from "@opal/icons";
import { taskDetailPath } from "@/app/craft/v1/tasks/constants";
import { formatAbsolute } from "@/app/craft/v1/tasks/utils";
import type { ScheduledRunContextResponse } from "@/app/craft/v1/tasks/interfaces";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";

interface ScheduledRunBannerProps {
  sessionId: string | null;
}

/**
 * Banner rendered above the transcript when the active session was created by
 * a scheduled task. When the session is interactive, this returns ``null``
 * (no DOM is inserted).
 *
 * Uses ``useSWR`` so the per-session lookup is deduped across the chat panel
 * and the parent layout.
 */
export default function ScheduledRunBanner({
  sessionId,
}: ScheduledRunBannerProps) {
  // 404 is the expected "this session isn't scheduled" signal — the standard
  // fetcher throws on it, which lands in `error` and falls through the
  // `if (!data)` guard below to render nothing. `shouldRetryOnError: false`
  // keeps SWR from hammering the endpoint after a legit 404.
  const { data } = useSWR<ScheduledRunContextResponse>(
    sessionId ? SWR_KEYS.scheduledRunContext(sessionId) : null,
    errorHandlingFetcher,
    { revalidateOnFocus: false, shouldRetryOnError: false }
  );

  if (!data) return null;

  return (
    <div
      className="flex items-center gap-2 px-4 py-2 bg-status-info-01 border-b border-border-01"
      data-testid="scheduled-run-banner"
    >
      <SvgClock size={16} className="text-status-info-05" />
      <Text mainUiBody text05 className="flex-1 truncate">
        This session was started by scheduled task{" "}
        <span className="font-main-ui-action">{data.task_name}</span> at{" "}
        {formatAbsolute(data.started_at)}.
      </Text>
      <Button
        icon={SvgArrowLeft}
        variant="default"
        prominence="tertiary"
        size="sm"
        href={taskDetailPath(data.task_id)}
        data-testid="back-to-task-button"
      >
        Back to task
      </Button>
    </div>
  );
}
