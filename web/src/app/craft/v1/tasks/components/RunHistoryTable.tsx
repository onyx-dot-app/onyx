"use client";

import { useCallback, useState } from "react";
import useSWR from "swr";
import { useRouter } from "next/navigation";
import Text from "@/refresh-components/texts/Text";
import { Button, Tooltip } from "@opal/components";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import { Section } from "@/layouts/general-layouts";
import { cn } from "@opal/utils";
import { listScheduledTaskRuns } from "@/app/craft/v1/tasks/api";
import { RunStatusBadge } from "@/app/craft/v1/tasks/components/StatusBadge";
import {
  buildSessionPath,
  RUNS_PAGE_SIZE,
} from "@/app/craft/v1/tasks/constants";
import type {
  ScheduledRunSummary,
  ScheduledTaskRunStatus,
} from "@/app/craft/v1/tasks/interfaces";
import {
  formatAbsolute,
  formatRelativeShort,
  formatRunDuration,
} from "@/app/craft/v1/tasks/utils";

interface RunHistoryTableProps {
  taskId: string;
}

const CLICKABLE_STATUSES: ReadonlySet<ScheduledTaskRunStatus> = new Set([
  "succeeded",
  "failed",
]);

const ROW_BLOCKED_TOOLTIP: Partial<Record<ScheduledTaskRunStatus, string>> = {
  queued: "Run not started yet.",
  running: "Run in progress — sessions can be opened once it finishes.",
  awaiting_approval: "Awaiting approval — open after the run resumes.",
  skipped: "Skipped — no session was created.",
};

export default function RunHistoryTable({ taskId }: RunHistoryTableProps) {
  const router = useRouter();
  const [pages, setPages] = useState<ScheduledRunSummary[][]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);

  const { data, error, isLoading, mutate } = useSWR(
    ["scheduled-task-runs", taskId],
    async () => {
      const res = await listScheduledTaskRuns(taskId, {
        limit: RUNS_PAGE_SIZE,
      });
      setPages([res.items]);
      setNextCursor(res.next_cursor);
      return res;
    },
    { revalidateOnFocus: false }
  );

  const loadMore = useCallback(async () => {
    if (!nextCursor) return;
    setLoadingMore(true);
    try {
      const res = await listScheduledTaskRuns(taskId, {
        cursor: nextCursor,
        limit: RUNS_PAGE_SIZE,
      });
      setPages((prev) => [...prev, res.items]);
      setNextCursor(res.next_cursor);
    } finally {
      setLoadingMore(false);
    }
  }, [nextCursor, taskId]);

  const refresh = useCallback(() => {
    void mutate();
  }, [mutate]);

  if (isLoading && !data) {
    return (
      <div className="flex justify-center py-8">
        <SimpleLoader className="h-6 w-6" />
      </div>
    );
  }

  if (error) {
    return (
      <Section gap={0.5}>
        <Text mainUiBody text03>
          Failed to load run history.
        </Text>
        <Button
          variant="default"
          prominence="secondary"
          onClick={refresh}
          size="sm"
        >
          Try again
        </Button>
      </Section>
    );
  }

  const allRuns = pages.flat();

  if (allRuns.length === 0) {
    return (
      <Text mainUiBody text03 className="py-6 text-center">
        No runs yet. The task will create one each time it fires, or use Run Now
        above.
      </Text>
    );
  }

  return (
    <Section gap={0.5}>
      {/* Header */}
      <div className="grid grid-cols-[1.2fr_0.8fr_0.6fr_2fr_0.6fr] gap-3 px-3 py-2 border-b border-border-01">
        <Text figureSmallLabel text03>
          Started
        </Text>
        <Text figureSmallLabel text03>
          Status
        </Text>
        <Text figureSmallLabel text03>
          Duration
        </Text>
        <Text figureSmallLabel text03>
          Summary
        </Text>
        <Text figureSmallLabel text03>
          Trigger
        </Text>
      </div>
      {/* Rows */}
      {allRuns.map((run) => {
        const clickable =
          CLICKABLE_STATUSES.has(run.status) && !!run.session_id;
        const blockTooltip = ROW_BLOCKED_TOOLTIP[run.status];

        const rowContent = (
          <div
            className={cn(
              "grid grid-cols-[1.2fr_0.8fr_0.6fr_2fr_0.6fr] gap-3 px-3 py-3 rounded-08 border border-transparent",
              clickable
                ? "hover:bg-background-tint-01 hover:border-border-02 cursor-pointer"
                : "cursor-not-allowed opacity-80"
            )}
            data-testid={`run-row-${run.id}`}
            data-run-status={run.status}
            onClick={() => {
              if (!clickable || !run.session_id) return;
              router.push(buildSessionPath(run.session_id));
            }}
          >
            <div className="flex flex-col">
              <Text mainUiBody text05>
                {formatAbsolute(run.started_at)}
              </Text>
              <Text secondaryBody text03>
                {formatRelativeShort(run.started_at)}
              </Text>
            </div>
            <div className="flex items-center">
              <RunStatusBadge status={run.status} />
            </div>
            <Text mainUiBody text03>
              {formatRunDuration(run.started_at, run.finished_at)}
            </Text>
            <Text mainUiBody text03 className="truncate">
              {run.summary ?? run.skip_reason ?? run.error_class ?? "—"}
            </Text>
            <Text mainUiBody text03>
              {run.trigger_source === "manual_run_now" ? "Run Now" : "Schedule"}
            </Text>
          </div>
        );

        if (!clickable && blockTooltip) {
          return (
            <Tooltip key={run.id} tooltip={blockTooltip} side="top">
              {rowContent}
            </Tooltip>
          );
        }
        return <div key={run.id}>{rowContent}</div>;
      })}

      {nextCursor && (
        <div className="flex justify-center pt-2">
          <Button
            variant="default"
            prominence="secondary"
            onClick={() => void loadMore()}
            disabled={loadingMore}
          >
            {loadingMore ? "Loading..." : "Load more"}
          </Button>
        </div>
      )}
    </Section>
  );
}
