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
  type PaginatedIndexAttempts,
} from "@/lib/connectors/types";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { ccPairStatusTag } from "@/views/admin/connectors/ConnectorDetailPage/statusTag";
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
/** One column of the card: a figure or tag over its two-line label. */
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

/** The pair at a glance: status, latest and total documents, its last run, and documents indexed over time. */
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
  // Waits for the latest attempt, so a running pair never flashes as indexed.
  if (latestIndexAttempts === undefined && error === undefined) {
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
      ? ccPair.overall_indexing_speed.toLocaleString(locale, {
          minimumFractionDigits: 2,
          maximumFractionDigits: 2,
        })
      : null;
  const recent = latestIndexAttempt?.total_docs_indexed ?? 0;
  const lastIndexed = t("lastIndexed.value", {
    when: timeAgo(ccPair.last_indexed, locale) ?? "-",
  });
  // The rate is the connector's average over every run, where a run row shows one run's live rate.
  const showsSpeed = !paused && hold === null && speed !== null;
  // A paused pair names only its last run. Others lead with the card's title.
  const statusLine = paused
    ? lastIndexed
    : t("statusLine", {
        detail:
          hold !== null
            ? t(`hold.${hold.reason}`)
            : speed === null
              ? lastIndexed
              : t("indexingSpeed", { speed }),
      });

  const chart = !FIRST_RUN_STATUSES.has(ccPair.status);
  // Before the first run, or while it is held, there is no recent run to count.
  const totalOnly = !chart || hold !== null;

  // The stage details popover spans the card, so the card is its anchor.
  return (
    <Popover>
      <Popover.Anchor asChild>
        <Card
          border="solid"
          rounding={4}
          padding={2}
          data-testid="connector-indexing-status"
        >
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
                      {statusLine}
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
              <StatBlock>
                <Section
                  flexDirection="row"
                  justifyContent="start"
                  alignItems="end"
                  gap={1}
                  width="fit"
                  height="fit"
                >
                  <Text font="main-content-emphasis" color="text-04">
                    {(totalOnly
                      ? ccPair.num_docs_indexed
                      : recent
                    ).toLocaleString(locale)}
                  </Text>
                  {!totalOnly && (
                    <Text font="main-content-body" color="text-04">
                      {t("documents.total", {
                        total: ccPair.num_docs_indexed.toLocaleString(locale),
                      })}
                    </Text>
                  )}
                </Section>
                <Text font="secondary-body" color="text-03">
                  {totalOnly ? t("documents.totalLabel") : t("documents.label")}
                </Text>
                {!totalOnly && (
                  <Text font="secondary-body" color="text-03">
                    {t("documentsIndexed.label")}
                  </Text>
                )}
              </StatBlock>
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
      </Popover.Anchor>
      {latestIndexAttempt !== undefined && (
        <StageDetailsPopoverContent indexAttemptId={latestIndexAttempt.id} />
      )}
    </Popover>
  );
}
