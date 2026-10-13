"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import useSWR, { mutate } from "swr";
import {
  Card,
  Dropdown,
  FilterButton,
  InputTypeIn,
  MessageCard,
  Pagination,
  Tag,
} from "@opal/components";
import { useDebouncedValue } from "@opal/hooks";
import { IllustrationContent, Section, toast } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import { CardLoader, IconLoader } from "@opal/loaders";
import {
  SvgActivity,
  SvgCheckCircle,
  SvgClock,
  SvgPlayCircle,
  SvgXOctagon,
} from "@opal/icons";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { buildCCPairInfoUrl } from "@/lib/connectors/utils";
import { cancelIndexAttempt } from "@/lib/connectors/svc";
import type {
  CCPairRun,
  CCPairRunKind,
  CCPairRunsResponse,
  CCPairRunStatusGroup,
} from "@/lib/connectors/types";
import ExceptionTraceModal from "@/sections/modals/PreviewModal/ExceptionTraceModal";
import RunRow, {
  RUN_KIND_ICONS,
  runErrorText,
} from "@/views/admin/connectors/ConnectorDetailPage/RunRow";
import StageMetricsModal from "@/views/admin/connectors/ConnectorDetailPage/StageMetricsModal";

const PAGE_SIZE = 10;
const RUNS_POLL_MS = 5000;
// Typing waits this long before it searches.
const SEARCH_DELAY_MS = 300;

/** The windows the time filter offers, in hours. `null` is all time. */
const WINDOWS = [
  { id: "all", hours: null },
  { id: "h12", hours: 12 },
  { id: "h24", hours: 24 },
  { id: "d7", hours: 24 * 7 },
  { id: "d30", hours: 24 * 30 },
] as const;
type TimeWindow = (typeof WINDOWS)[number];

interface PickedWindow {
  window: TimeWindow;
  /** Fixed when the window is picked, so polling keeps one cache key. */
  since: string | null;
}
const ALL_TIME: PickedWindow = { window: WINDOWS[0], since: null };
const LOADER_ROWS = 3;

const STATUS_GROUPS: CCPairRunStatusGroup[] = [
  "running",
  "succeeded",
  "failed",
  "canceled",
];

// The header counts. Canceled runs get none.
const COUNT_TAGS = [
  { group: "succeeded", icon: SvgCheckCircle, color: "green" },
  { group: "running", icon: IconLoader, color: "blue" },
  { group: "failed", icon: SvgXOctagon, color: "red" },
] as const;

const ALL = "all";

export interface RunsCardProps {
  ccPairId: number;
  /** Shows the cancel action on running or queued index attempts. */
  canOperate: boolean;
}

/** The pair's index attempts and, when perm-synced, its permission syncs, newest first. */
export default function RunsCard({ ccPairId, canOperate }: RunsCardProps) {
  const t = useTranslations("admin.connector.runs");
  const [page, setPage] = useState(1);
  const [picked, setPicked] = useState<PickedWindow>(ALL_TIME);
  const [kind, setKind] = useState<CCPairRunKind | null>(null);
  const [statusGroup, setStatusGroup] = useState<CCPairRunStatusGroup | null>(
    null
  );
  const [searchInput, setSearchInput] = useState("");
  const search = useDebouncedValue(searchInput.trim(), SEARCH_DELAY_MS);
  const [logRun, setLogRun] = useState<CCPairRun | null>(null);
  const [stagesAttemptId, setStagesAttemptId] = useState<number | null>(null);

  const key = SWR_KEYS.ccPairRuns(ccPairId, {
    pageNum: page - 1,
    pageSize: PAGE_SIZE,
    since: picked.since,
    kinds: kind === null ? null : [kind],
    statusGroups: statusGroup === null ? null : [statusGroup],
    q: search,
  });
  const { data, error, isLoading } = useSWR<CCPairRunsResponse>(
    key,
    errorHandlingFetcher,
    { refreshInterval: RUNS_POLL_MS, keepPreviousData: true }
  );

  function pickWindow(window: TimeWindow) {
    setPicked({
      window,
      since:
        window.hours === null
          ? null
          : new Date(Date.now() - window.hours * 3_600_000).toISOString(),
    });
    setPage(1);
  }

  function pickKind(next: CCPairRunKind | null) {
    setKind(next);
    setPage(1);
  }

  function pickStatusGroup(next: CCPairRunStatusGroup | null) {
    setStatusGroup(next);
    setPage(1);
  }

  async function cancel(run: CCPairRun) {
    const failure = await cancelIndexAttempt(
      run.attempt.id,
      t("toasts.cancelFailed")
    );
    if (failure !== null) {
      toast.error(failure);
      return;
    }
    toast.success(t("toasts.canceled"));
    await Promise.all([mutate(key), mutate(buildCCPairInfoUrl(ccPairId))]);
  }

  const kinds = data?.kinds ?? ["indexing"];
  const totalItems = data?.total_items ?? 0;
  const totalPages = Math.max(1, Math.ceil(totalItems / PAGE_SIZE));
  // Polling can shrink the feed under an open page.
  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);
  const filtered =
    kind !== null ||
    statusGroup !== null ||
    picked.since !== null ||
    search !== "";

  return (
    <Card border="solid" rounding={4} padding={2}>
      {logRun !== null && (
        <ExceptionTraceModal
          onOutsideClick={() => setLogRun(null)}
          exceptionTrace={runErrorText(logRun) ?? ""}
          title={t(`errorModal.${logRun.kind}`)}
        />
      )}
      {stagesAttemptId !== null && (
        <StageMetricsModal
          indexAttemptId={stagesAttemptId}
          onClose={() => setStagesAttemptId(null)}
        />
      )}
      <Section alignItems="stretch" gap={2} height="fit">
        <Section
          flexDirection="row"
          justifyContent="between"
          gap={2}
          height="fit"
        >
          <Section height="fit" className="min-w-0 flex-1">
            <InputTypeIn
              searchIcon
              variant="internal"
              placeholder={t("search.placeholder")}
              value={searchInput}
              onChange={(event) => {
                setSearchInput(event.target.value);
                setPage(1);
              }}
            />
          </Section>
          <Section
            flexDirection="row"
            justifyContent="end"
            gap={1}
            width="fit"
            height="fit"
          >
            {COUNT_TAGS.map(({ group, icon, color }) => (
              <Tag
                key={group}
                icon={icon}
                title={String(data?.status_counts[group] ?? 0)}
                tooltip={t(`counts.${group}`, {
                  count: data?.status_counts[group] ?? 0,
                })}
                color={color}
              />
            ))}
          </Section>
        </Section>

        <Section
          flexDirection="row"
          justifyContent="start"
          gap={1}
          height="fit"
          wrap
        >
          <Dropdown>
            <Dropdown.Trigger asChild>
              <FilterButton
                icon={SvgClock}
                active={picked.since !== null}
                onClear={() => pickWindow(ALL_TIME.window)}
              >
                {t(`window.${picked.window.id}`)}
              </FilterButton>
            </Dropdown.Trigger>
            <Dropdown.Data
              label={t("window.label")}
              value={picked.window.id}
              onSelect={(option) => {
                const window = WINDOWS.find((w) => w.id === option.value);
                if (window !== undefined) pickWindow(window);
              }}
              items={WINDOWS.map((option) => ({
                kind: "option" as const,
                value: option.id,
                title: t(`window.${option.id}`),
              }))}
            />
          </Dropdown>
          {kinds.length > 1 && (
            <Dropdown>
              <Dropdown.Trigger asChild>
                <FilterButton
                  icon={SvgPlayCircle}
                  active={kind !== null}
                  onClear={() => pickKind(null)}
                >
                  {kind === null ? t("kinds.all") : t(`kinds.${kind}`)}
                </FilterButton>
              </Dropdown.Trigger>
              <Dropdown.Data
                label={t("kinds.label")}
                value={kind ?? ALL}
                onSelect={(option) =>
                  pickKind(
                    kinds.find((candidate) => candidate === option.value) ??
                      null
                  )
                }
                items={[
                  {
                    kind: "option" as const,
                    value: ALL,
                    title: t("kinds.all"),
                  },
                  ...kinds.map((candidate) => ({
                    kind: "option" as const,
                    value: candidate,
                    icon: RUN_KIND_ICONS[candidate],
                    title: t(`kinds.${candidate}`),
                  })),
                ]}
              />
            </Dropdown>
          )}
          <Dropdown>
            <Dropdown.Trigger asChild>
              <FilterButton
                icon={SvgActivity}
                active={statusGroup !== null}
                onClear={() => pickStatusGroup(null)}
              >
                {statusGroup === null
                  ? t("statusGroups.all")
                  : t(`statusGroups.${statusGroup}`)}
              </FilterButton>
            </Dropdown.Trigger>
            <Dropdown.Data
              label={t("statusGroups.label")}
              value={statusGroup ?? ALL}
              onSelect={(option) =>
                pickStatusGroup(
                  STATUS_GROUPS.find((group) => group === option.value) ?? null
                )
              }
              items={[
                {
                  kind: "option" as const,
                  value: ALL,
                  title: t("statusGroups.all"),
                },
                ...STATUS_GROUPS.map((group) => ({
                  kind: "option" as const,
                  value: group,
                  title: t(`statusGroups.${group}`),
                })),
              ]}
            />
          </Dropdown>
        </Section>

        {error !== undefined ? (
          <MessageCard variant="error" title={t("loadError.title")} />
        ) : isLoading && data === undefined ? (
          <Section alignItems="stretch" gap={1} height="fit">
            {Array.from({ length: LOADER_ROWS }, (_, index) => (
              <CardLoader
                key={index}
                color="background-tint-00"
                border="none"
                rounding={2}
                padding={2}
              />
            ))}
          </Section>
        ) : (data?.items.length ?? 0) === 0 ? (
          <IllustrationContent
            illustration={SvgNoResult}
            title={filtered ? t("empty.filteredTitle") : t("empty.title")}
            description={filtered ? undefined : t("empty.description")}
          />
        ) : (
          <Section alignItems="stretch" gap={1} height="fit">
            {data?.items.map((run) => (
              <RunRow
                key={`${run.kind}-${run.attempt.id}`}
                run={run}
                canCancel={canOperate}
                onCancel={() => void cancel(run)}
                onViewLogs={() => setLogRun(run)}
                onViewStages={() => setStagesAttemptId(run.attempt.id)}
              />
            ))}
          </Section>
        )}

        {totalItems > PAGE_SIZE && (
          <Pagination
            variant="count"
            currentPage={page}
            totalPages={totalPages}
            pageSize={PAGE_SIZE}
            totalItems={totalItems}
            onChange={setPage}
            units={t("units", { count: totalItems })}
            size="sm"
          />
        )}
      </Section>
    </Card>
  );
}
