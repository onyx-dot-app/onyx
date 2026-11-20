"use client";

import { useRef, useState, type ReactNode } from "react";
import useSWR, { mutate } from "swr";
import { useTranslations } from "next-intl";
import {
  Button,
  Table,
  Text,
  Tooltip,
  type TableColumn,
} from "@opal/components";
import { Section, toast } from "@opal/layouts";
import { SvgLongWait } from "@opal/illustrations";
import UnseenMarker from "@/app/craft/components/UnseenMarker";
import { formatRunDuration, isRunUnviewed } from "@/app/craft/v1/tasks/utils";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { useAppPosition } from "@/lib/navigation/hooks";
import {
  revalidateChatScheduledRunViews,
  useScheduledTaskFormat,
} from "@/lib/scheduledTasks/hooks";
import {
  listScheduledTaskRuns,
  markScheduledRunsViewed,
} from "@/lib/scheduledTasks/svc";
import type {
  ScheduledRunListResponse,
  ScheduledRunSummary,
} from "@/lib/scheduledTasks/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import { CustomizeEmpty } from "@/sections/customize/CustomizeList";
import { RunStatusBadge } from "@/sections/scheduledTasks/StatusBadges";

const RUNS_PAGE_SIZE = 50;
const RUNS_MAX_PAGE_SIZE = 100;
const REFRESH_INTERVAL_MS = 5000;

type ClosedReason = "queued" | "skipped" | "craft";

/** Why a run has no chat to open, or null when it has one. */
function closedReason(run: ScheduledRunSummary): ClosedReason | null {
  if (run.chat_session_id) return null;
  if (run.status === "QUEUED" || run.status === "RUNNING") return "queued";
  if (run.status === "SKIPPED") return "skipped";
  return "craft";
}

interface ClosedCellProps {
  run: ScheduledRunSummary;
  children: ReactNode;
}

function ClosedCell({ run, children }: ClosedCellProps) {
  const t = useTranslations("scheduledTasks.runs.closed");
  const reason = closedReason(run);
  if (!reason) return <>{children}</>;
  return (
    <Tooltip tooltip={t(reason)} side="top">
      <div data-run-closed className="w-full cursor-not-allowed opacity-60">
        {children}
      </div>
    </Tooltip>
  );
}

interface ScheduledRunHistoryProps {
  taskId: string;
}

export default function ScheduledRunHistory({
  taskId,
}: ScheduledRunHistoryProps) {
  const t = useTranslations("scheduledTasks.runs");
  const tTasks = useTranslations("scheduledTasks");
  const appPosition = useAppPosition();
  const timeFormat = useScheduledTaskFormat();
  const [olderPages, setOlderPages] = useState<ScheduledRunSummary[][]>([]);
  const [olderCursor, setOlderCursor] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [markingViewed, setMarkingViewed] = useState(false);
  const unviewedSignature = useRef<string | null>(null);

  const { data, error, isLoading } = useSWR<ScheduledRunListResponse>(
    SWR_KEYS.chatScheduledTaskRunsPage(taskId, RUNS_PAGE_SIZE),
    errorHandlingFetcher,
    {
      refreshInterval: REFRESH_INTERVAL_MS,
      // The sidebar polls slowly, so tell it when a run turns unviewed.
      onSuccess: (page) => {
        const unviewed = page.items
          .filter(isRunUnviewed)
          .map((run) => `${run.id}:${run.revision}`)
          .join();
        if (unviewedSignature.current === unviewed) return;
        unviewedSignature.current = unviewed;
        void mutate(SWR_KEYS.chatScheduledTasksUnviewedCount);
      },
    }
  );
  const { data: unviewedProbe } = useSWR<ScheduledRunListResponse>(
    SWR_KEYS.chatScheduledTaskHasUnviewedRuns(taskId),
    errorHandlingFetcher,
    { refreshInterval: REFRESH_INTERVAL_MS }
  );

  const runs: ScheduledRunSummary[] = [];
  const seen = new Set<string>();
  for (const run of [...(data?.items ?? []), ...olderPages.flat()]) {
    if (seen.has(run.id)) continue;
    seen.add(run.id);
    runs.push(run);
  }
  const loadMoreCursor =
    olderPages.length > 0 ? olderCursor : (data?.next_cursor ?? null);
  const hasUnviewed =
    runs.some(isRunUnviewed) ||
    (unviewedProbe?.items.some(isRunUnviewed) ?? false);

  async function loadMore() {
    if (!loadMoreCursor) return;
    setLoadingMore(true);
    try {
      const page = await listScheduledTaskRuns(taskId, {
        cursor: loadMoreCursor,
        limit: RUNS_PAGE_SIZE,
      });
      setOlderPages((pages) => [...pages, page.items]);
      setOlderCursor(page.next_cursor);
    } catch {
      toast.error(t("loadFailed"));
    } finally {
      setLoadingMore(false);
    }
  }

  async function markAllViewed() {
    setMarkingViewed(true);
    const viewed = new Map<string, ScheduledRunSummary>();
    try {
      // A marked run leaves the unviewed filter, so each pass reads the next batch.
      for (;;) {
        const page = await listScheduledTaskRuns(taskId, {
          limit: RUNS_MAX_PAGE_SIZE,
          unviewed: true,
        });
        if (page.items.length === 0) break;
        const res = await markScheduledRunsViewed(taskId, page.items);
        for (const run of res.items) viewed.set(run.id, run);
        if (page.items.length < RUNS_MAX_PAGE_SIZE) break;
      }
    } catch {
      toast.error(t("markAllViewedFailed"));
    } finally {
      if (viewed.size > 0) {
        setOlderPages((pages) =>
          pages.map((page) => page.map((run) => viewed.get(run.id) ?? run))
        );
        await revalidateChatScheduledRunViews(taskId).catch(() => undefined);
      }
      setMarkingViewed(false);
    }
  }

  const columns: TableColumn<ScheduledRunSummary>[] = [
    {
      kind: "data",
      field: "started_at",
      title: t("columns.started"),
      weight: 26,
      cell: (startedAt, row) => (
        <ClosedCell run={row}>
          <Section
            flexDirection="row"
            justifyContent="start"
            height="auto"
            gap={1.5}
          >
            {isRunUnviewed(row) && (
              <UnseenMarker
                label={tTasks("unviewedResults")}
                className="shrink-0"
              />
            )}
            <Tooltip tooltip={timeFormat.relative(startedAt)} side="top">
              <Text font="main-ui-body" color="text-04" maxLines={1}>
                {timeFormat.absolute(startedAt)}
              </Text>
            </Tooltip>
          </Section>
        </ClosedCell>
      ),
    },
    {
      kind: "data",
      field: "status",
      title: t("columns.status"),
      weight: 18,
      cell: (status, row) => (
        <ClosedCell run={row}>
          <div data-run-status={status}>
            <RunStatusBadge status={status} />
          </div>
        </ClosedCell>
      ),
    },
    {
      kind: "display",
      id: "duration",
      title: t("columns.duration"),
      width: { weight: 12 },
      cell: (row) => (
        <ClosedCell run={row}>
          <Text font="main-ui-body" color="text-03" maxLines={1}>
            {formatRunDuration(row.started_at, row.finished_at)}
          </Text>
        </ClosedCell>
      ),
    },
    {
      kind: "display",
      id: "trigger",
      title: t("columns.trigger"),
      width: { weight: 14 },
      cell: (row) => (
        <ClosedCell run={row}>
          <Text font="main-ui-body" color="text-03" maxLines={1}>
            {t("trigger", { source: row.trigger_source })}
          </Text>
        </ClosedCell>
      ),
    },
    {
      kind: "display",
      id: "detail",
      title: t("columns.detail"),
      width: { weight: 30 },
      cell: (row) => (
        <ClosedCell run={row}>
          <Text
            font="main-ui-body"
            color="text-03"
            maxLines={1}
            overflowTooltip
          >
            {row.summary ??
              (row.error_class
                ? t("errorClass", { errorClass: row.error_class })
                : (row.skip_reason ?? ""))}
          </Text>
        </ClosedCell>
      ),
    },
  ];

  if (isLoading && !data)
    return (
      <Text as="p" font="main-ui-body" color="text-03">
        {t("loading")}
      </Text>
    );
  if (error && !data)
    return (
      <Text as="p" font="main-ui-body" color="status-error-05">
        {t("loadFailed")}
      </Text>
    );
  if (runs.length === 0)
    return (
      <CustomizeEmpty
        illustration={SvgLongWait}
        title={t("empty.title")}
        description={t("empty.description")}
      />
    );

  return (
    <Section gap={2} alignItems="stretch" height="auto">
      <Section flexDirection="row" justifyContent="end" height="auto">
        <Button
          prominence="tertiary"
          size="sm"
          disabled={markingViewed || !hasUnviewed}
          onClick={() => void markAllViewed()}
        >
          {t("markAllViewed")}
        </Button>
      </Section>
      <Table
        label={t("label")}
        items={runs}
        columns={columns}
        getRowId={(row) => row.id}
        pageSize={false}
        onRowClick={(row) => {
          if (row.chat_session_id) appPosition.openChat(row.chat_session_id);
        }}
        getRowLabel={(row) =>
          t("open", { time: timeFormat.absolute(row.started_at) })
        }
      />
      {loadMoreCursor && (
        <Section height="auto">
          <Button
            prominence="secondary"
            disabled={loadingMore}
            onClick={() => void loadMore()}
          >
            {t("loadMore")}
          </Button>
        </Section>
      )}
    </Section>
  );
}
