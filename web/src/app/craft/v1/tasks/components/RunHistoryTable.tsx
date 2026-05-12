"use client";

import { useCallback, useMemo, useState } from "react";
import useSWR from "swr";
import { useRouter } from "next/navigation";
import Text from "@/refresh-components/texts/Text";
import { Button, Table, createTableColumns } from "@opal/components";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import { Section } from "@/layouts/general-layouts";
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

const CLICKABLE_STATUSES: ReadonlySet<ScheduledTaskRunStatus> =
  new Set<ScheduledTaskRunStatus>(["succeeded", "failed"]);

const tc = createTableColumns<ScheduledRunSummary>();

function buildColumns() {
  return [
    tc.column("started_at", {
      header: "Started",
      weight: 22,
      enableSorting: false,
      cell: (value) => (
        <div className="flex flex-col gap-0.5">
          <Text mainUiBody text05 nowrap>
            {formatAbsolute(value)}
          </Text>
          <Text secondaryBody text03>
            {formatRelativeShort(value)}
          </Text>
        </div>
      ),
    }),
    tc.column("status", {
      header: "Status",
      weight: 14,
      enableSorting: false,
      cell: (status) => (
        // Wrapper exposes the status to Playwright (and lets the row's
        // ``onRowClick`` still navigate via event bubbling).
        <div data-run-status={status}>
          <RunStatusBadge status={status} />
        </div>
      ),
    }),
    tc.displayColumn({
      id: "duration",
      header: "Duration",
      width: { weight: 12 },
      cell: (row) => (
        <Text mainUiBody text03 nowrap>
          {formatRunDuration(row.started_at, row.finished_at)}
        </Text>
      ),
    }),
    tc.displayColumn({
      id: "summary",
      header: "Summary",
      width: { weight: 38 },
      cell: (row) => (
        <Text mainUiBody text03>
          {row.summary ?? row.skip_reason ?? row.error_class ?? "—"}
        </Text>
      ),
    }),
    tc.column("trigger_source", {
      header: "Trigger",
      weight: 14,
      enableSorting: false,
      cell: (value) => (
        <Text mainUiBody text03 nowrap>
          {value === "manual_run_now" ? "Run Now" : "Schedule"}
        </Text>
      ),
    }),
  ];
}

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

  const columns = useMemo(() => buildColumns(), []);

  const allRuns = pages.flat();

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

  if (allRuns.length === 0) {
    return (
      <Text mainUiBody text03 className="py-6 text-center">
        No runs yet. The task will create one each time it fires, or use Run Now
        above.
      </Text>
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
          if (CLICKABLE_STATUSES.has(row.status) && row.session_id) {
            router.push(buildSessionPath(row.session_id));
          }
        }}
      />
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
