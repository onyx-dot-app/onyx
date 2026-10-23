"use client";

import { useLocale, useTranslations } from "next-intl";
import useSWR from "swr";
import { Button, Card, Popover, Tag, Text, Tooltip } from "@opal/components";
import { Section } from "@opal/layouts";
import {
  SvgListCheck,
  SvgOrganization,
  SvgPlayCircle,
  SvgUsers,
} from "@opal/icons";
import { CardLoader } from "@opal/loaders";
import { timeAgo } from "@opal/time";
import type { RichStr } from "@opal/types";
import {
  ConnectorCredentialPairStatus,
  type CCPairFullInfo,
  type CCPairRun,
  type PaginatedIndexAttempts,
} from "@/lib/connectors/types";
import type { AccessType } from "@/lib/types";
import { isPermSynced } from "@/lib/connectors/accessType";
import { useLatestCCPairRun } from "@/lib/connectors/ccPair/hooks";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  attemptStatusTag,
  ccPairStatusTag,
  runStatusTag,
  type StatusTag,
} from "@/views/admin/connectors/ConnectorDetailPage/statusTag";
import {
  RATE_FORMAT,
  RunWarningsTag,
  isActive,
  useSyncRateLabel,
} from "@/views/admin/connectors/ConnectorDetailPage/RunRow";
import StatusTagPill from "@/views/admin/connectors/ConnectorDetailPage/StatusTagPill";
import StageDetailsPopoverContent, {
  StageDetailsTrigger,
} from "@/views/admin/connectors/ConnectorDetailPage/StageDetailsPopover";
import ThroughputChart, {
  ThroughputWindowPicker,
  PAIR_WINDOWS,
  type PickerWindow,
  type SliceRange,
} from "@/views/admin/connectors/ConnectorDetailPage/ThroughputChart";

// Statuses a pair keeps until its first index succeeds, a failed first run included.
const FIRST_RUN_STATUSES = new Set<ConnectorCredentialPairStatus>([
  ConnectorCredentialPairStatus.SCHEDULED,
  ConnectorCredentialPairStatus.INITIAL_INDEXING,
]);

interface StatBlockProps {
  title?: string | RichStr;
  children: React.ReactNode;
}
/** One column of a card: a titled status tag, or a figure over its label. */
function StatBlock({ title, children }: StatBlockProps) {
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
      {title !== undefined && (
        <Text font="secondary-action" color="text-04">
          {title}
        </Text>
      )}
      {children}
    </Section>
  );
}

interface FigureStatBlockProps {
  value: number;
  label: string | RichStr;
}
function FigureStatBlock({ value, label }: FigureStatBlockProps) {
  const locale = useLocale();
  return (
    <StatBlock>
      <Text font="main-content-emphasis" color="text-04">
        {value.toLocaleString(locale)}
      </Text>
      <Text font="secondary-body" color="text-03">
        {label}
      </Text>
    </StatBlock>
  );
}

// Matches the page's own poll of the pair.
const POLL_MS = 5000;

interface SyncStatBlockProps {
  title: string | RichStr;
  /** The sync's newest run, undefined before its first. */
  run: CCPairRun | undefined;
  /** The pair's last successful sync of this kind, null until one succeeds. */
  lastSynced: string | null;
  /** The pair's Paused tag while it is paused. A paused pair starts no sync, so it outranks all but a queued or running one. */
  pausedTag: StatusTag | null;
  /** The sync starts only once the pair's first index succeeds. */
  waitsForFirstIndex: boolean;
}
/** A permission sync's column: its newest run's tag over its live rate or its last success. */
function SyncStatBlock({
  title,
  run,
  lastSynced,
  pausedTag,
  waitsForFirstIndex,
}: SyncStatBlockProps) {
  const t = useTranslations("admin.connector.statusCard.sync");
  const locale = useLocale();
  const syncRateLabel = useSyncRateLabel();
  const shownRun =
    pausedTag !== null && run !== undefined && !isActive(run) ? undefined : run;
  // A success can outlive its run: an old sync, or a shared group sync logged on a since-deleted pair.
  function tag(): StatusTag {
    if (shownRun !== undefined) return runStatusTag(shownRun);
    if (pausedTag !== null) return pausedTag;
    return attemptStatusTag(lastSynced === null ? null : "success", true);
  }
  const liveRate = shownRun === undefined ? null : syncRateLabel(shownRun);
  const neverSynced = liveRate === null && lastSynced === null;
  function detail(): string {
    if (liveRate !== null) return liveRate;
    if (lastSynced !== null) {
      return t("last", { when: timeAgo(lastSynced, locale) ?? "-" });
    }
    return t(waitsForFirstIndex ? "waitingForFirstIndex" : "never");
  }
  return (
    <StatBlock title={title}>
      <Section
        flexDirection="row"
        justifyContent="start"
        gap={1}
        width="fit"
        height="fit"
      >
        <StatusTagPill tag={tag()} />
        {shownRun !== undefined && <RunWarningsTag run={shownRun} />}
      </Section>
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

interface AccessStatBlockProps {
  accessType: AccessType;
}
/** Who reads the documents of a pair that syncs no permissions. */
function AccessStatBlock({ accessType }: AccessStatBlockProps) {
  const t = useTranslations("admin.connector.statusCard");
  const tAccess = useTranslations(
    "admin.connectorsList.settings.documentAccess"
  );
  const everyone = accessType === "public";
  return (
    <StatBlock title={t("accessTitle")}>
      <Tag
        icon={everyone ? SvgOrganization : SvgUsers}
        title={tAccess(everyone ? "everyone.title" : "specificGroups.title")}
        color="gray"
        variant="status"
        font="secondary-body"
      />
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

/** The pair at a glance: its indexing and permission sync statuses or its document access, then its documents and documents indexed over time. */
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
  const locale = useLocale();
  const hold = ccPair.indexing_hold;
  const { data: latestIndexAttempts, error } = useSWR<PaginatedIndexAttempts>(
    SWR_KEYS.ccPairLatestIndexAttempt(ccPair.id),
    errorHandlingFetcher,
    { refreshInterval: POLL_MS }
  );
  const permSynced = isPermSynced(ccPair.access_type);
  const docSync = useLatestCCPairRun(
    ccPair.id,
    "doc_permission_sync",
    permSynced,
    POLL_MS
  );
  const groupSync = useLatestCCPairRun(
    ccPair.id,
    "group_sync",
    permSynced,
    POLL_MS
  );
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
  const firstRun = FIRST_RUN_STATUSES.has(ccPair.status);
  const status = ccPairStatusTag(
    ccPair.status,
    ccPair.in_repeated_error_state,
    latestIndexAttempt?.status
  );
  const pausedTag = paused ? status : null;
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

  // Each sync kind the pair's source runs gets a column.
  const showsDocSync =
    docSync.data?.kinds.includes("doc_permission_sync") ?? false;
  const showsGroupSync = groupSync.data?.kinds.includes("group_sync") ?? false;
  const docSyncRun = docSync.data?.items[0];
  const groupSyncRun = groupSync.data?.items[0];
  // A paused pair's counts stay as its last runs left them.
  const syncedDocs =
    docSyncRun?.kind === "doc_permission_sync"
      ? docSyncRun.attempt.total_docs_synced
      : null;
  const syncedMemberships =
    groupSyncRun?.kind === "group_sync"
      ? groupSyncRun.attempt.total_group_memberships_synced
      : null;
  // The chart waits for the first successful index, and a paused pair's counts no longer move.
  const chart = !firstRun && !paused;
  // Before the first index succeeds, the card shows only documents a run already indexed.
  const showsDocuments = !firstRun || ccPair.num_docs_indexed > 0;

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
              <StatBlock title={t("title")}>
                <Section
                  flexDirection="row"
                  justifyContent="start"
                  gap={1}
                  width="fit"
                  height="fit"
                >
                  <StatusTagPill tag={status} />
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
              {!permSynced && (
                <AccessStatBlock accessType={ccPair.access_type} />
              )}
              {showsDocSync && (
                <SyncStatBlock
                  title={t("sync.permissionsTitle")}
                  run={docSyncRun}
                  lastSynced={ccPair.last_time_perm_sync}
                  pausedTag={pausedTag}
                  waitsForFirstIndex={firstRun}
                />
              )}
              {/* A group sync needs no index, so it can run during the first one. */}
              {showsGroupSync && (
                <SyncStatBlock
                  title={t("sync.groupsTitle")}
                  run={groupSyncRun}
                  lastSynced={ccPair.last_time_external_group_sync}
                  pausedTag={pausedTag}
                  waitsForFirstIndex={false}
                />
              )}
            </Section>
          </Card>
        </Popover.Anchor>
        {latestIndexAttempt !== undefined && (
          <StageDetailsPopoverContent indexAttemptId={latestIndexAttempt.id} />
        )}
      </Popover>
      {showsDocuments && (
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
              <FigureStatBlock
                value={ccPair.num_docs_indexed}
                label={t("documents.totalLabel")}
              />
              {paused && showsDocSync && syncedDocs !== null && (
                <FigureStatBlock
                  value={syncedDocs}
                  label={t("documents.syncedPermissionsLabel")}
                />
              )}
              {paused && showsGroupSync && syncedMemberships !== null && (
                <FigureStatBlock
                  value={syncedMemberships}
                  label={t("documents.syncedMembershipsLabel")}
                />
              )}
              {chart && (
                <>
                  <FigureStatBlock
                    value={recent}
                    label={t("documents.recentLabel")}
                  />
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
                </>
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
      )}
    </Section>
  );
}
