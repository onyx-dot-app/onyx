"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import useSWR from "swr";
import { useRouter } from "next/navigation";
import {
  Button,
  Table,
  Text,
  Tooltip,
  createTableColumns,
} from "@opal/components";
import SvgLock from "@opal/icons/lock";
import { SvgSimpleLoader } from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import { listScheduledTaskRuns } from "@/app/craft/v1/tasks/api";
import { RunStatusBadge } from "@/app/craft/v1/tasks/components/StatusBadge";
import {
  buildSessionPath,
  RUNS_PAGE_SIZE,
} from "@/app/craft/v1/tasks/constants";
import type {
  ScheduledRunListResponse,
  ScheduledRunSummary,
} from "@/app/craft/v1/tasks/interfaces";
import {
  formatAbsolute,
  formatRelativeShort,
  formatRunDuration,
  getNonClickableReason,
} from "@/app/craft/v1/tasks/utils";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";

interface RunHistoryTableProps {
  taskId: string;
}

const tc = createTableColumns<ScheduledRunSummary>();
const RUN_HISTORY_REFRESH_INTERVAL_MS = 5000;

interface NonClickableCellProps {
  reason: string | null;
  children: ReactNode;
}

// Wraps a cell's content so non-clickable rows get a clear "you can't click
// this" affordance: dimmed content, ``not-allowed`` cursor, and a tooltip
// explaining why. Clickable rows pass through unchanged.
function NonClickableCell({ reason, children }: NonClickableCellProps) {
  if (!reason) return <>{children}</>;
  return (
    <Tooltip tooltip={reason} side="top" delayDuration={150}>
      <div
        data-non-clickable="true"
        className="flex w-full cursor-not-allowed items-center opacity-60"
      >
        {children}
      </div>
    </Tooltip>
  );
}

function buildColumns() {
  return [
    tc.column("started_at", {
      header: "Started",
      weight: 22,
      enableSorting: false,
      cell: (value, row) => (
        <NonClickableCell reason={getNonClickableReason(row)}>
          <div className="flex flex-col gap-0.5">
            <Text font="main-ui-body" color="text-05" nowrap>
              {formatAbsolute(value)}
            </Text>
            <Text font="secondary-body" color="text-03">
              {formatRelativeShort(value)}
            </Text>
          </div>
        </NonClickableCell>
      ),
    }),
    tc.column("status", {
      header: "Status",
      weight: 14,
      enableSorting: false,
      cell: (status, row) => {
        const reason = getNonClickableReason(row);
        return (
          // Wrapper exposes the status to Playwright (and lets the row's
          // ``onRowClick`` still navigate via event bubbling).
          <NonClickableCell reason={reason}>
            <div
              data-run-status={status}
              className="inline-flex items-center gap-1.5"
            >
              <RunStatusBadge status={status} />
              {reason && (
                <SvgLock
                  size={12}
                  className="text-text-03"
                  aria-label="Not openable"
                />
              )}
            </div>
          </NonClickableCell>
        );
      },
    }),
    tc.displayColumn({
      id: "duration",
      header: "Duration",
      width: { weight: 12 },
      cell: (row) => (
        <NonClickableCell reason={getNonClickableReason(row)}>
          <Text font="main-ui-body" color="text-03" nowrap>
            {formatRunDuration(row.started_at, row.finished_at)}
          </Text>
        </NonClickableCell>
      ),
    }),
    tc.displayColumn({
      id: "summary",
      header: "Summary",
      width: { weight: 38 },
      cell: (row) => (
        <NonClickableCell reason={getNonClickableReason(row)}>
          <Text font="main-ui-body" color="text-03">
            {row.summary ?? row.skip_reason ?? row.error_class ?? "—"}
          </Text>
        </NonClickableCell>
      ),
    }),
    tc.column("trigger_source", {
      header: "Trigger",
      weight: 14,
      enableSorting: false,
      cell: (value, row) => (
        <NonClickableCell reason={getNonClickableReason(row)}>
          <Text font="main-ui-body" color="text-03" nowrap>
            {value === "MANUAL_RUN_NOW" ? "Run Now" : "Schedule"}
          </Text>
        </NonClickableCell>
      ),
    }),
  ];
}

export default function RunHistoryTable({ taskId }: RunHistoryTableProps) {
  const router = useRouter();
  const [olderPages, setOlderPages] = useState<ScheduledRunSummary[][]>([]);
  const [olderNextCursor, setOlderNextCursor] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);

  const firstPageUrl = `${SWR_KEYS.scheduledTaskRuns(
    taskId
  )}?limit=${RUNS_PAGE_SIZE}`;
  const { data, error, isLoading, mutate } = useSWR<ScheduledRunListResponse>(
    firstPageUrl,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      refreshInterval: RUN_HISTORY_REFRESH_INTERVAL_MS,
    }
  );

  useEffect(() => {
    setOlderPages([]);
    setOlderNextCursor(null);
  }, [taskId]);

  const loadMoreCursor =
    olderPages.length > 0 ? olderNextCursor : (data?.next_cursor ?? null);

  const loadMore = useCallback(async () => {
    if (!loadMoreCursor) return;
    setLoadingMore(true);
    try {
      const res = await listScheduledTaskRuns(taskId, {
        cursor: loadMoreCursor,
        limit: RUNS_PAGE_SIZE,
      });
      setOlderPages((prev) => [...prev, res.items]);
      setOlderNextCursor(res.next_cursor);
    } finally {
      setLoadingMore(false);
    }
  }, [loadMoreCursor, taskId]);

  const refresh = useCallback(() => {
    void mutate();
  }, [mutate]);

  const columns = useMemo(() => buildColumns(), []);

  const allRuns = useMemo(() => {
    const runs: ScheduledRunSummary[] = [];
    const seenRunIds = new Set<string>();

    for (const run of data?.items ?? []) {
      runs.push(run);
      seenRunIds.add(run.id);
    }

    for (const page of olderPages) {
      for (const run of page) {
        if (seenRunIds.has(run.id)) continue;
        runs.push(run);
        seenRunIds.add(run.id);
      }
    }

    return runs;
  }, [data?.items, olderPages]);

  if (isLoading && !data) {
    return (
      <div className="flex justify-center py-8">
        <SvgSimpleLoader className="h-6 w-6" />
      </div>
    );
  }

  if (error) {
    return (
      <Section gap={0.5}>
        <Text font="main-ui-body" color="text-03">
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

  if (allRuns.length === 0) {
    return (
      <div className="py-6 text-center">
        <Text font="main-ui-body" color="text-03">
          No runs yet. The task will create one each time it fires, or use Run
          Now above.
        </Text>
      </div>
    );
  }

  return (
    <Section gap={0.5} alignItems="stretch">
      <Table
        data={allRuns}
        columns={columns}
        getRowId={(row) => row.id}
        selectionBehavior="single-select"
        onRowClick={(row) => {
          if (!getNonClickableReason(row) && row.session_id) {
            router.push(buildSessionPath(row.session_id));
          }
        }}
      />
      {loadMoreCursor && (
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
