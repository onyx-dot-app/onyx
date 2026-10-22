"use client";

import { useLocale, useTranslations } from "next-intl";
import useSWR from "swr";
import { Button, Card, Popover, Tag, Text, Tooltip } from "@opal/components";
import { Section } from "@opal/layouts";
import { SvgListCheck, SvgPlayCircle } from "@opal/icons";
import { CardLoader } from "@opal/loaders";
import { timeAgo } from "@opal/time";
import {
  ConnectorCredentialPairStatus,
  type CCPairFullInfo,
  type CCPairRun,
  type CCPairRunKind,
  type CCPairRunsResponse,
  type PaginatedIndexAttempts,
} from "@/lib/connectors/types";
import { isPermSynced } from "@/lib/connectors/accessType";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  attemptStatusTag,
  ccPairStatusTag,
  runStatusTag,
} from "@/views/admin/connectors/ConnectorDetailPage/statusTag";
import {
  RATE_FORMAT,
  useSyncRateLabel,
} from "@/views/admin/connectors/ConnectorDetailPage/RunRow";
import StageDetailsPopoverContent, {
  StageDetailsTrigger,
} from "@/views/admin/connectors/ConnectorDetailPage/StageDetailsPopover";
import ThroughputChart, {
  ThroughputWindowPicker,
  PAIR_WINDOWS,
  type PickerWindow,
  type SliceRange,
} from "@/views/admin/connectors/ConnectorDetailPage/ThroughputChart";

// The chart waits for the pair's first successful run.
const FIRST_RUN_STATUSES = new Set<ConnectorCredentialPairStatus>([
  ConnectorCredentialPairStatus.SCHEDULED,
  ConnectorCredentialPairStatus.INITIAL_INDEXING,
]);

interface StatBlockProps {
  children: React.ReactNode;
}
/** One column of a card: a title, status tag and detail line, or a figure over its label. */
function StatBlock({ children }: StatBlockProps) {
  return (
    // Columns share the row evenly and wrap below 12rem, so three fit at 640px.
    <Section
      alignItems="start"
      justifyContent="start"
      gap={1}
      padding={2}
      width="auto"
      height="fit"
      className="grow basis-0 min-w-48"
    >
      {children}
    </Section>
  );
}

// Matches the page's own poll of the pair.
const POLL_MS = 5000;

type SyncRunKind = Extract<CCPairRunKind, "doc_permission_sync" | "group_sync">;

/** The pair's newest run of one kind. The response's `kinds` lists every kind the pair runs. */
function useLatestRun(ccPairId: number, kind: SyncRunKind, enabled: boolean) {
  return useSWR<CCPairRunsResponse>(
    enabled
      ? SWR_KEYS.ccPairRuns(ccPairId, {
          pageNum: 0,
          pageSize: 1,
          since: null,
          until: null,
          kinds: [kind],
          statusGroups: null,
          q: "",
          errors: null,
          superseded: null,
          resolved: null,
        })
      : null,
    errorHandlingFetcher,
    { refreshInterval: POLL_MS }
  );
}

interface SyncStatBlockProps {
  title: string;
  /** The sync's newest run, undefined before its first. */
  run: CCPairRun | undefined;
  /** The pair's last successful sync of this kind, null until one succeeds. */
  lastSynced: string | null;
}
/** A permission sync's column: its newest run's tag over its live rate or its last success. */
function SyncStatBlock({ title, run, lastSynced }: SyncStatBlockProps) {
  const t = useTranslations("admin.connector.statusCard.sync");
  const tBadges = useTranslations("admin.status.badges");
  const locale = useLocale();
  const syncRateLabel = useSyncRateLabel();
  // A pair can have a success with no run of its own: an old sync, or a shared group sync another pair ran.
  const tag =
    run !== undefined
      ? runStatusTag(run)
      : attemptStatusTag(lastSynced === null ? null : "success", true);
  const liveRate = run === undefined ? null : syncRateLabel(run);
  const neverSynced = liveRate === null && lastSynced === null;
  function detail(): string {
    if (liveRate !== null) return liveRate;
    if (lastSynced === null) return t("never");
    return t("last", { when: timeAgo(lastSynced, locale) ?? "-" });
  }
  return (
    <StatBlock>
      <Text font="secondary-action" color="text-04">
        {title}
      </Text>
      <Tag
        icon={tag.icon}
        title={tBadges(tag.labelKey)}
        color={tag.color}
        variant="status"
        font="secondary-body"
      />
      <Tooltip tooltip={neverSynced ? t("neverTooltip") : undefined} side="top">
        <Section width="fit" height="fit">
          <Text font="secondary-body" color="text-03">
            {detail()}
          </Text>
        </Section>
      </Tooltip>
    </StatBlock>
  );
}

export interface StatusCardProps {
  ccPair: CCPairFullInfo;
  /** Backs the Start Indexing button shown while failed checks hold the pair's first run; null hides it. */
  onStartIndexing: (() => void) | null;
  startingIndexing: boolean;
  /** Opens the checks card, from the checks icon a held pair shows in place of its stages. */
  onViewChecks: () => void;
  /** The page's time window, shared with the runs card. */
  timeWindow: PickerWindow;
  onTimeWindowChange: (window: PickerWindow) => void;
  /** The span of the chart the page is narrowed to: a click or drag on the chart picks one, the chip's X clears it. */
  range?: SliceRange | null;
  onRangeChange?: (range: SliceRange | null) => void;
}

/** The pair at a glance: its indexing and permission sync statuses, then its documents and documents indexed over time. */
export default function StatusCard({
  ccPair,
  onStartIndexing,
  startingIndexing,
  onViewChecks,
  timeWindow,
  onTimeWindowChange,
  range = null,
  onRangeChange,
}: StatusCardProps) {
  const t = useTranslations("admin.connector.statusCard");
  const tBadges = useTranslations("admin.status.badges");
  const locale = useLocale();
  const hold = ccPair.indexing_hold;
  const { data: latestIndexAttempts, error } = useSWR<PaginatedIndexAttempts>(
    SWR_KEYS.ccPairLatestIndexAttempt(ccPair.id),
    errorHandlingFetcher,
    { refreshInterval: POLL_MS }
  );
  const permSynced = isPermSynced(ccPair.access_type);
  const docSync = useLatestRun(ccPair.id, "doc_permission_sync", permSynced);
  const groupSync = useLatestRun(ccPair.id, "group_sync", permSynced);
  // Waits for the latest attempt, so a running pair never flashes as indexed, and for the sync runs, so the columns land together.
  if (
    (latestIndexAttempts === undefined && error === undefined) ||
    (permSynced &&
      [docSync, groupSync].some(
        (sync) => sync.data === undefined && sync.error === undefined
      ))
  ) {
    return <CardLoader descriptionLines={2} />;
  }
  const latestIndexAttempt = latestIndexAttempts?.items[0];
  const paused = ccPair.status === ConnectorCredentialPairStatus.PAUSED;
  const status = ccPairStatusTag(
    ccPair.status,
    ccPair.in_repeated_error_state,
    latestIndexAttempt?.status
  );
  const speed =
    ccPair.indexing &&
    ccPair.overall_indexing_speed !== null &&
    ccPair.num_docs_indexed > 0
      ? ccPair.overall_indexing_speed.toLocaleString(locale, RATE_FORMAT)
      : null;
  const recent = latestIndexAttempt?.total_docs_indexed ?? 0;
  const lastIndexed = t("lastIndexed.value", {
    when: timeAgo(ccPair.last_indexed, locale) ?? "-",
  });
  // The rate is the connector's average over every run, where a run row shows one run's live rate.
  const showsSpeed = !paused && hold === null && speed !== null;
  // A paused pair names only its last run.
  function statusLine(): string {
    if (paused) return lastIndexed;
    if (hold !== null) return t(`hold.${hold.reason}`);
    return speed === null ? lastIndexed : t("indexingSpeed", { speed });
  }

  const chart = !FIRST_RUN_STATUSES.has(ccPair.status);
  // Before the first run, or while it is held, there is no recent run to count.
  const totalOnly = !chart || hold !== null;

  // Each sync kind the pair's source runs gets a column.
  const showsDocSync =
    docSync.data?.kinds.includes("doc_permission_sync") ?? false;
  const showsGroupSync = groupSync.data?.kinds.includes("group_sync") ?? false;

  return (
    <Section
      alignItems="stretch"
      gap={2}
      height="fit"
      data-testid="connector-indexing-status"
    >
      {/* The stage details popover spans the status card, so that card is its anchor. */}
      <Popover>
        <Popover.Anchor asChild>
          <Card border="solid" rounding={4} padding={2}>
            <Section
              flexDirection="row"
              alignItems="start"
              justifyContent="start"
              gap={1}
              height="fit"
              wrap
            >
              <StatBlock>
                <Text font="secondary-action" color="text-04">
                  {t("title")}
                </Text>
                <Section
                  flexDirection="row"
                  justifyContent="start"
                  gap={1}
                  width="fit"
                  height="fit"
                >
                  <Tag
                    icon={status.icon}
                    title={tBadges(status.labelKey)}
                    color={status.color}
                    variant="status"
                    font="secondary-body"
                  />
                  {hold !== null ? (
                    <Button
                      icon={SvgListCheck}
                      prominence="internal"
                      size="xs"
                      tooltip={t("hold.viewChecks")}
                      aria-label={t("hold.viewChecks")}
                      onClick={onViewChecks}
                    />
                  ) : (
                    latestIndexAttempt !== undefined &&
                    !paused && <StageDetailsTrigger />
                  )}
                </Section>
                <Tooltip
                  tooltip={showsSpeed ? t("indexingSpeedTooltip") : undefined}
                  side="top"
                >
                  <Section width="fit" height="fit">
                    <Text font="secondary-body" color="text-03">
                      {statusLine()}
                    </Text>
                  </Section>
                </Tooltip>
                {/* A run in flight ends on its own; the other holds wait for the admin. */}
                {hold !== null &&
                  hold.reason !== "checks_running" &&
                  onStartIndexing !== null && (
                    <Button
                      icon={SvgPlayCircle}
                      prominence="secondary"
                      size="sm"
                      disabled={startingIndexing}
                      onClick={onStartIndexing}
                    >
                      {t("hold.start")}
                    </Button>
                  )}
              </StatBlock>
              {showsDocSync && (
                <SyncStatBlock
                  title={t("sync.permissionsTitle")}
                  run={docSync.data?.items[0]}
                  lastSynced={ccPair.last_time_perm_sync}
                />
              )}
              {showsGroupSync && (
                <SyncStatBlock
                  title={t("sync.groupsTitle")}
                  run={groupSync.data?.items[0]}
                  lastSynced={ccPair.last_time_external_group_sync}
                />
              )}
            </Section>
          </Card>
        </Popover.Anchor>
        {latestIndexAttempt !== undefined && (
          <StageDetailsPopoverContent indexAttemptId={latestIndexAttempt.id} />
        )}
      </Popover>
      <Card border="solid" rounding={4} padding={2}>
        <Section alignItems="stretch" gap={1} height="fit">
          <Section
            flexDirection="row"
            alignItems="start"
            justifyContent="start"
            gap={1}
            height="fit"
            wrap
          >
            <StatBlock>
              <Text font="main-content-emphasis" color="text-04">
                {ccPair.num_docs_indexed.toLocaleString(locale)}
              </Text>
              <Text font="secondary-body" color="text-03">
                {t("documents.totalLabel")}
              </Text>
            </StatBlock>
            {!totalOnly && (
              <StatBlock>
                <Text font="main-content-emphasis" color="text-04">
                  {recent.toLocaleString(locale)}
                </Text>
                <Text font="secondary-body" color="text-03">
                  {t("documents.recentLabel")}
                </Text>
              </StatBlock>
            )}
            {chart && (
              <Section
                flexDirection="row"
                justifyContent="end"
                alignItems="center"
                gap={1}
                width="auto"
                height="fit"
                className="grow basis-0"
                wrap
              >
                <ThroughputWindowPicker
                  windows={PAIR_WINDOWS}
                  value={timeWindow}
                  onChange={onTimeWindowChange}
                  selection={range}
                  onClearSelection={
                    onRangeChange === undefined
                      ? undefined
                      : () => onRangeChange(null)
                  }
                />
              </Section>
            )}
          </Section>
          {chart && (
            // The chart sits 12px in from the card's sides and 8px from the row above.
            <Section
              padding={2}
              alignItems="stretch"
              height="fit"
              className="mx-1"
            >
              <ThroughputChart
                ccPairId={ccPair.id}
                range={timeWindow}
                selection={range}
                onRangeSelect={onRangeChange}
              />
            </Section>
          )}
        </Section>
      </Card>
    </Section>
  );
}
