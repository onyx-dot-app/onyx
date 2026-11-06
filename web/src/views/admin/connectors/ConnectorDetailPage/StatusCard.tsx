"use client";

import { useState, type ReactNode } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Button, Card, Popover, SelectButton, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import {
  SvgListCheck,
  SvgPanelRight,
  SvgPlayCircle,
  SvgScissors,
} from "@opal/icons";
import { CardLoader } from "@opal/loaders";
import { timeAgo } from "@opal/time";
import type { IconFunctionComponent, RichStr } from "@opal/types";
import { cn } from "@opal/utils";
import {
  ConnectorCredentialPairStatus,
  type CCPairFullInfo,
  type CCPairRun,
  type CCPairRunKind,
  type CCPairRunsResponse,
} from "@/lib/connectors/types";
import type { IndexAttemptSnapshot } from "@/lib/types";
import { isPermSynced } from "@/lib/connectors/accessType";
import {
  CC_PAIR_STATUS_POLL_MS,
  useLatestCCPairRun,
  useLatestIndexAttempt,
} from "@/lib/connectors/ccPair/hooks";
import {
  attemptStatusTag,
  ccPairStatusTag,
  runStatusTag,
  type StatusTag,
} from "@/views/admin/connectors/ConnectorDetailPage/statusTag";
import {
  ErrorCountTag,
  RunWarningsTag,
  isActive,
  useLiveRunDetail,
} from "@/views/admin/connectors/ConnectorDetailPage/RunRow";
import StatusTagPill from "@/views/admin/connectors/ConnectorDetailPage/StatusTagPill";
import { RunDetailsHint } from "@/views/admin/connectors/ConnectorDetailPage/InlineDetails";
import { LineFigure } from "@/views/admin/connectors/shared/LineLayout";
import StageDetailsPopoverContent, {
  StageDetailsTrigger,
} from "@/views/admin/connectors/ConnectorDetailPage/StageDetailsPopover";
import LineLayout from "@/views/admin/connectors/shared/LineLayout";

// Statuses a pair keeps until its first index succeeds, a failed first run included.
const FIRST_RUN_STATUSES = new Set<ConnectorCredentialPairStatus>([
  ConnectorCredentialPairStatus.SCHEDULED,
  ConnectorCredentialPairStatus.INITIAL_INDEXING,
]);

/** The feed's newest run, narrowed to `kind` so its attempt fields type. */
function latestRun<K extends CCPairRunKind>(
  response: CCPairRunsResponse | undefined,
  kind: K
): Extract<CCPairRun, { kind: K }> | undefined {
  const run = response?.items[0];
  return run !== undefined && isRunOfKind(run, kind) ? run : undefined;
}

function isRunOfKind<K extends CCPairRunKind>(
  run: CCPairRun,
  kind: K
): run is Extract<CCPairRun, { kind: K }> {
  return run.kind === kind;
}

/** The card reads the pair's latest attempt, so it wraps it as a run for the run line's readers. */
function indexRunOf(
  attempt: IndexAttemptSnapshot
): Extract<CCPairRun, { kind: "indexing" }> {
  return {
    kind: "indexing",
    time_created: attempt.time_started ?? attempt.time_updated,
    attempt,
    resolved_at: null,
    superseded: false,
  };
}

/** "-" stands in for a time the pair has not recorded. */
function ago(iso: string | null, locale: string): string {
  return timeAgo(iso, locale) ?? "-";
}

interface FigureProps {
  value: number;
  label: string | RichStr;
}

/** A count over its label that holds the design's 188px, so a wider picker label beside it never moves it. */
export function FigureStatBlock({ value, label }: FigureProps) {
  return (
    <Section
      alignItems="start"
      gap={1}
      padding={2}
      width="auto"
      height="fit"
      className="min-w-[11.75rem] shrink-0 basis-[11.75rem]"
    >
      <LineFigure value={value} label={label} />
    </Section>
  );
}

/** A card's count, 24 px down so its value sits on the tag line and its label on the detail. Once the line wraps it sits under the column. */
function CardFigure(props: FigureProps) {
  return (
    <Section
      alignItems="start"
      gap={0}
      height="fit"
      className="mt-6 @max-[38.75rem]:mt-0"
    >
      <LineFigure {...props} />
    </Section>
  );
}

interface StatusColumnProps {
  title: string | RichStr;
  /** The tag line: the status tag, its hints and its error count. */
  tags: ReactNode;
  detail: string | RichStr;
  children?: ReactNode;
}
/** Column A: label and tag line at fixed heights, so the B count's offset lands its value on the tag line. */
function StatusColumn({ title, tags, detail, children }: StatusColumnProps) {
  return (
    <Section alignItems="start" gap={0} height="fit">
      <Section alignItems="start" height={1.25}>
        <Text font="secondary-action" color="text-04">
          {title}
        </Text>
      </Section>
      <Section
        flexDirection="row"
        justifyContent="start"
        gap={1}
        width="fit"
        height={1.75}
      >
        {tags}
      </Section>
      <Text font="secondary-body" color="text-03">
        {detail}
      </Text>
      {children}
    </Section>
  );
}

interface HintButtonProps {
  icon: IconFunctionComponent;
  label: string;
  onClick: () => void;
}
/** A tag-line hint in the stage hint's style, for a target that opens elsewhere. */
function HintButton({ icon, label, onClick }: HintButtonProps) {
  return (
    <RunDetailsHint icon={icon} label={label} open={null} onClick={onClick} />
  );
}

/** Both cards draw the design's 96 px: 7 px of padding inside the 1 px border around the 80 px line. */
const CARD_PADDING = 1.75;

export interface StatusCardProps {
  ccPair: CCPairFullInfo;
  /** Backs the Start Indexing button shown while failed checks hold the pair's first run; null hides it. */
  onStartIndexing: (() => void) | null;
  startingIndexing: boolean;
  /** Opens the checks card, from the checks icon a held pair shows in place of its stages. */
  onViewChecks: () => void;
  /** Opens the Indexing tab at a run, from the status tag or a prune or checks hint. */
  onOpenRun: (id: number, kind: CCPairRunKind) => void;
  /** Shows the Activities panel with its errors in view, focused on the index run that holds them when there is one. */
  onFocusErrors: (attemptId: number | null) => void;
  /** Whether the Activities panel shows, which selects the panel button. */
  panelOpen: boolean;
  onTogglePanel: () => void;
  /** Hides the panel button where the panel cannot hide. */
  panelButtonClassName?: string;
}

interface IndexingCardProps extends StatusCardProps {
  status: StatusTag;
  latestAttempt: IndexAttemptSnapshot | undefined;
  pruneRun: CCPairRun | undefined;
  checkRun: CCPairRun | undefined;
}

/** The pair's indexing: its status with the latest runs a click away, its documents and the panel button. */
function IndexingCard({
  ccPair,
  status,
  latestAttempt,
  pruneRun,
  checkRun,
  onStartIndexing,
  startingIndexing,
  onViewChecks,
  onOpenRun,
  onFocusErrors,
  panelOpen,
  onTogglePanel,
  panelButtonClassName,
}: IndexingCardProps) {
  const t = useTranslations("admin.connector");
  const tActions = useTranslations("admin.indexing.list.actions");
  const locale = useLocale();
  const liveDetail = useLiveRunDetail();
  const [stagesOpen, setStagesOpen] = useState(false);
  const hold = ccPair.indexing_hold;
  const paused = ccPair.status === ConnectorCredentialPairStatus.PAUSED;
  const indexing =
    !paused && hold === null && latestAttempt?.status === "in_progress";
  // A run that ends while its stages are open takes the popover with its trigger.
  if (stagesOpen && !indexing) setStagesOpen(false);
  const lastIndexed = t("statusCard.lastIndexed.value", {
    when: ago(ccPair.last_indexed, locale),
  });
  // The queue position and a deletion's start time are not on this page's data, so those states read the last index too.
  function detail(): string {
    if (paused) return lastIndexed;
    if (hold !== null) return t(`statusCard.hold.${hold.reason}`);
    if (!indexing || latestAttempt === undefined) return lastIndexed;
    return liveDetail(indexRunOf(latestAttempt)) ?? lastIndexed;
  }
  const panelLabel = t(
    panelOpen
      ? "statusCard.actions.hideActivities"
      : "statusCard.actions.showActivities"
  );

  // One hint set at a time, by what the admin can act on: a held pair's checks, a live run's stages, else the latest prune and check runs, and none while paused.
  function hints(): ReactNode {
    if (paused) return null;
    if (hold !== null) {
      return (
        <HintButton
          icon={SvgListCheck}
          label={t("statusCard.hold.viewChecks")}
          onClick={onViewChecks}
        />
      );
    }
    if (indexing) return <StageDetailsTrigger open={stagesOpen} />;
    return (
      <>
        {pruneRun !== undefined && (
          <HintButton
            icon={SvgScissors}
            label={t("statusCard.actions.viewPruningRun")}
            onClick={() => onOpenRun(pruneRun.attempt.id, pruneRun.kind)}
          />
        )}
        {checkRun !== undefined && (
          <HintButton
            icon={SvgListCheck}
            label={t("statusCard.actions.viewChecksRun")}
            onClick={() => onOpenRun(checkRun.attempt.id, checkRun.kind)}
          />
        )}
      </>
    );
  }

  return (
    // The stage details popover spans the card, so the card is its anchor.
    <Popover open={stagesOpen} onOpenChange={setStagesOpen}>
      <Popover.Anchor asChild>
        <Card
          border="solid"
          rounding={4}
          padding={CARD_PADDING}
          data-testid="status-card"
        >
          <LineLayout
            variant="row"
            a={
              <StatusColumn
                title={t("statusCard.title")}
                tags={
                  <>
                    <StatusTagPill
                      tag={status}
                      size={6}
                      action={
                        latestAttempt === undefined
                          ? undefined
                          : {
                              tooltip: t("statusCard.actions.viewIndexingRun"),
                              onClick: () =>
                                onOpenRun(latestAttempt.id, "indexing"),
                            }
                      }
                    />
                    {hints()}
                    <ErrorCountTag
                      count={latestAttempt?.open_error_count ?? 0}
                      tooltip={tActions("viewErrors")}
                      onClick={() => onFocusErrors(latestAttempt?.id ?? null)}
                    />
                  </>
                }
                detail={detail()}
              >
                {/* A run in flight ends on its own. The other holds wait for the admin. */}
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
                      {t("statusCard.hold.start")}
                    </Button>
                  )}
              </StatusColumn>
            }
            b={
              <CardFigure
                value={ccPair.num_docs_indexed}
                label={t("statusCard.documents.indexedLabel")}
              />
            }
            c={null}
            d={
              <Section
                width="fit"
                height="fit"
                className={cn("mt-1", panelButtonClassName)}
              >
                <SelectButton
                  icon={SvgPanelRight}
                  variant="select-light"
                  state={panelOpen ? "selected" : "empty"}
                  size="md"
                  tooltip={panelLabel}
                  aria-label={panelLabel}
                  aria-pressed={panelOpen}
                  onClick={onTogglePanel}
                />
              </Section>
            }
          />
        </Card>
      </Popover.Anchor>
      {latestAttempt !== undefined && (
        <StageDetailsPopoverContent indexAttemptId={latestAttempt.id} />
      )}
    </Popover>
  );
}

interface PermissionsSyncCardProps {
  ccPair: CCPairFullInfo;
  docSyncRun: Extract<CCPairRun, { kind: "doc_permission_sync" }> | undefined;
  groupSyncRun: Extract<CCPairRun, { kind: "group_sync" }> | undefined;
  /** The source syncs group memberships, which fill the third column. */
  showsGroupSync: boolean;
  /** The runs feed failed, so the card falls back to the pair's own last sync status and shows no counts. */
  loadFailed: boolean;
  onFocusErrors: () => void;
}

/** The pair's document permission sync: its newest run's status, the documents it synced and the group memberships. */
function PermissionsSyncCard({
  ccPair,
  docSyncRun,
  groupSyncRun,
  showsGroupSync,
  loadFailed,
  onFocusErrors,
}: PermissionsSyncCardProps) {
  const t = useTranslations("admin.connector");
  const locale = useLocale();
  const liveDetail = useLiveRunDetail();
  const lastSynced = ccPair.last_time_perm_sync;
  // A paused pair starts no sync, so its Paused tag outranks all but a queued or running one.
  const pausedTag =
    ccPair.status === ConnectorCredentialPairStatus.PAUSED
      ? ccPairStatusTag(ccPair.status, ccPair.in_repeated_error_state, null)
      : null;
  const shownRun =
    pausedTag !== null && docSyncRun !== undefined && !isActive(docSyncRun)
      ? undefined
      : docSyncRun;
  // A success can outlive its run record, so the pair's last sync time still earns a Synced tag.
  function tag(): StatusTag {
    if (shownRun !== undefined) return runStatusTag(shownRun);
    if (pausedTag !== null) return pausedTag;
    if (loadFailed) {
      return attemptStatusTag(
        ccPair.last_permission_sync_attempt_status,
        "sync"
      );
    }
    return attemptStatusTag(lastSynced === null ? null : "success", "sync");
  }
  const shownTag = tag();
  // Synced permissions gate search, so a pair that never synced or whose sync failed says why its documents may not show.
  const unsearchable =
    shownTag.labelKey === "failed" ||
    (shownTag.labelKey === "scheduled" && lastSynced === null);
  function detail(): string {
    if (loadFailed) return t("runs.loadError.title");
    const live = shownRun === undefined ? null : liveDetail(shownRun);
    if (live !== null) return live;
    if (lastSynced !== null) {
      return t("statusCard.sync.last", { when: ago(lastSynced, locale) });
    }
    // The sync starts only once the pair's first index succeeds.
    return t(
      FIRST_RUN_STATUSES.has(ccPair.status)
        ? "statusCard.sync.waitingForFirstIndex"
        : "statusCard.sync.never"
    );
  }

  return (
    <Card
      border="solid"
      rounding={4}
      padding={CARD_PADDING}
      data-testid="status-card"
    >
      <LineLayout
        variant="row"
        a={
          <StatusColumn
            title={t("statusCard.sync.permissionsTitle")}
            tags={
              <>
                <StatusTagPill
                  tag={shownTag}
                  size={6}
                  tooltip={
                    unsearchable ? t("statusCard.sync.neverTooltip") : undefined
                  }
                />
                {shownRun !== undefined && (
                  <RunWarningsTag
                    run={shownRun}
                    // The panel lists open runs, so a resolved run's count has nothing to open.
                    onClick={
                      shownRun.resolved_at === null ? onFocusErrors : undefined
                    }
                  />
                )}
              </>
            }
            detail={detail()}
          />
        }
        b={
          !loadFailed && (
            <CardFigure
              value={docSyncRun?.attempt.total_docs_synced ?? 0}
              label={t("statusCard.sync.docsLabel")}
            />
          )
        }
        c={
          showsGroupSync &&
          !loadFailed && (
            <CardFigure
              value={groupSyncRun?.attempt.total_group_memberships_synced ?? 0}
              label={t("statusCard.sync.groupsLabel")}
            />
          )
        }
        d={null}
      />
    </Card>
  );
}

/** The pair at a glance: an Indexing card, then a Permissions Sync card for a pair with Sync access whose source syncs document permissions. */
export default function StatusCard(props: StatusCardProps) {
  const { ccPair } = props;
  const { data: latestIndexAttempts, error } = useLatestIndexAttempt(ccPair.id);
  const permSynced = isPermSynced(ccPair.access_type);
  const docSync = useLatestCCPairRun(
    ccPair.id,
    "doc_permission_sync",
    permSynced,
    CC_PAIR_STATUS_POLL_MS
  );
  const groupSync = useLatestCCPairRun(
    ccPair.id,
    "group_sync",
    permSynced,
    CC_PAIR_STATUS_POLL_MS
  );
  const prune = useLatestCCPairRun(
    ccPair.id,
    "pruning",
    true,
    CC_PAIR_STATUS_POLL_MS
  );
  const checks = useLatestCCPairRun(
    ccPair.id,
    "checks",
    true,
    CC_PAIR_STATUS_POLL_MS
  );
  // Waits for the latest attempt, so a running pair never flashes as indexed, and for the sync feeds, so the cards land together. The prune and check hints may follow.
  const feeds = permSynced ? [docSync, groupSync] : [];
  if (
    (latestIndexAttempts === undefined && error === undefined) ||
    feeds.some((feed) => feed.data === undefined && feed.error === undefined)
  ) {
    return <CardLoader descriptionLines={2} />;
  }
  const latestAttempt = latestIndexAttempts?.items[0];
  const status = ccPairStatusTag(
    ccPair.status,
    ccPair.in_repeated_error_state,
    latestAttempt?.status
  );
  // The feed lists every kind the pair runs, whatever kind it was asked for.
  const pairKinds = docSync.data?.kinds ?? [];
  // Without the feed the card cannot tell whether the source syncs, so a failed load still shows it rather than dropping it unexplained.
  const syncLoadFailed =
    permSynced && docSync.data === undefined && docSync.error !== undefined;

  return (
    <Section
      alignItems="stretch"
      gap={2}
      height="fit"
      data-testid="connector-indexing-status"
    >
      <IndexingCard
        {...props}
        status={status}
        latestAttempt={latestAttempt}
        pruneRun={latestRun(prune.data, "pruning")}
        checkRun={latestRun(checks.data, "checks")}
      />
      {(pairKinds.includes("doc_permission_sync") || syncLoadFailed) && (
        <PermissionsSyncCard
          ccPair={ccPair}
          docSyncRun={latestRun(docSync.data, "doc_permission_sync")}
          groupSyncRun={latestRun(groupSync.data, "group_sync")}
          // A group feed that failed has no count to show, which a 0 would misstate.
          showsGroupSync={
            pairKinds.includes("group_sync") && groupSync.data !== undefined
          }
          loadFailed={syncLoadFailed}
          onFocusErrors={() => props.onFocusErrors(null)}
        />
      )}
    </Section>
  );
}
