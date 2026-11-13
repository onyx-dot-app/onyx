"use client";

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent,
  type ReactNode,
} from "react";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import {
  Button,
  Card,
  Divider,
  Popover,
  SelectButton,
  Text,
  Tooltip,
} from "@opal/components";
import { Section } from "@opal/layouts";
import {
  SvgChevronDown,
  SvgChevronUp,
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
  useCCPairDocumentTypes,
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
import StageDetailsPopoverContent, {
  StageDetailsTrigger,
} from "@/views/admin/connectors/ConnectorDetailPage/StageDetailsPopover";
import LineLayout, {
  LineFigure,
  NO_FIGURE,
} from "@/views/admin/connectors/shared/LineLayout";
import {
  OTHER_DOCUMENT_TYPE,
  documentTypeLabel,
  documentTypeSlices,
  totalSize,
  type DocumentTypeSlice,
  type TypeColorsByPair,
} from "@/views/admin/connectors/ConnectorDetailPage/documentTypes";
import { formatBytes } from "@/lib/utils";

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

interface CardFigureProps extends FigureProps {
  /** Keeps the 24 px once the line wraps too, where the types bar opens above the count, so unfolding never moves it. */
  holdsBarRow?: boolean;
}

/** A card's count, 24 px down so its value sits on the tag line and its label on the detail. Once the line wraps it sits under the column. */
function CardFigure({ holdsBarRow = false, ...props }: CardFigureProps) {
  return (
    <Section
      alignItems="start"
      gap={0}
      height="fit"
      className={cn("mt-6", !holdsBarRow && "@max-[38.75rem]:mt-0")}
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

interface SizeParts {
  value: string;
  unit: string;
}

/** A size as its number in the admin's locale and its unit: `formatBytes` picks the unit, the card sets the two in separate fonts. */
function useSizeParts(): (bytes: number) => SizeParts {
  const t = useTranslations("admin.connector.statusCard.types");
  const format = useFormatter();
  return (bytes) => {
    const formatted = formatBytes(bytes, 1);
    const space = formatted.lastIndexOf(" ");
    const unit = formatted.slice(space + 1);
    return {
      value: format.number(parseFloat(formatted.slice(0, space)), {
        maximumFractionDigits: 1,
      }),
      unit: unit === "Bytes" ? t("bytes") : unit,
    };
  };
}

interface SummaryLineProps {
  value: string | RichStr;
  unit: string | RichStr;
}
/** A value in 14/20 semibold before its unit in 12/16. */
function SummaryLine({ value, unit }: SummaryLineProps) {
  return (
    <Section
      flexDirection="row"
      justifyContent="end"
      gap={0.5}
      width="fit"
      height="fit"
    >
      <Text font="main-ui-action" color="text-03">
        {value}
      </Text>
      <Text font="secondary-body" color="text-03">
        {unit}
      </Text>
    </Section>
  );
}

interface TypesSummaryProps {
  /** Null draws a dash for a breakdown that failed to load. */
  typeCount: number | null;
  /** Null hides the size, which shows only when every document reports one. */
  sizeBytes: number | null;
}
/** The type count over the total size, at the right of the card's figures. */
function TypesSummary({ typeCount, sizeBytes }: TypesSummaryProps) {
  const t = useTranslations("admin.connector.statusCard.types");
  const format = useFormatter();
  const sizeParts = useSizeParts();
  const size = sizeBytes === null ? null : sizeParts(sizeBytes);
  return (
    <Section alignItems="end" gap={0} width="fit" height="fit">
      <SummaryLine
        value={typeCount === null ? NO_FIGURE : format.number(typeCount)}
        unit={t("count", { count: typeCount ?? 0 })}
      />
      {typeCount === null && (
        <Text font="secondary-body" color="text-03">
          {t("loadError")}
        </Text>
      )}
      {size !== null && <SummaryLine value={size.value} unit={size.unit} />}
    </Section>
  );
}

interface TypeHover {
  hovered: string | null;
  onHover: (key: string | null) => void;
}

/** A segment or row cell of one type: it hovers its type and mutes while another type is hovered. */
function typeCellProps(
  key: string,
  { hovered, onHover }: TypeHover,
  className?: string
) {
  return {
    "data-document-type": key,
    className: cn(
      "transition-opacity",
      hovered !== null && hovered !== key && "opacity-50",
      className
    ),
    // A tap fires no leave until the next tap elsewhere, so touch never mutes.
    onPointerEnter: (event: PointerEvent) => {
      if (event.pointerType !== "touch") onHover(key);
    },
    onPointerLeave: () => onHover(null),
  };
}

/** Other is a word in the admin's language, every other slice its file type. */
function useSliceLabel(): (slice: DocumentTypeSlice) => string {
  const t = useTranslations("admin.connector.statusCard.types");
  return (slice) =>
    slice.key === OTHER_DOCUMENT_TYPE
      ? t("other")
      : documentTypeLabel(slice.key);
}

interface TypesBarProps {
  slices: DocumentTypeSlice[];
  hover: TypeHover;
}
/** One 8 px bar in a 20 px line, a segment per type sized by its count. The table below carries the same figures. */
function TypesBar({ slices, hover }: TypesBarProps) {
  return (
    <Section height={1.25} padding={0.5} aria-hidden>
      <Section flexDirection="row" gap={0.25} height={0.5}>
        {slices.map((slice) => (
          <div
            key={slice.key}
            data-testid="document-type-segment"
            {...typeCellProps(
              slice.key,
              hover,
              cn("h-full min-w-px basis-0 rounded-[1px]", slice.colorClass)
            )}
            style={{ flexGrow: slice.count }}
          />
        ))}
      </Section>
    </Section>
  );
}

interface TypeNameProps {
  slice: DocumentTypeSlice;
}
/** A type's 4 x 12 color mark before its name. */
function TypeName({ slice }: TypeNameProps) {
  const label = useSliceLabel();
  return (
    <Section
      flexDirection="row"
      justifyContent="start"
      gap={0}
      height="fit"
      className="min-w-0 max-w-full"
    >
      <Section width={0.5} height={1} className="shrink-0">
        <div className={cn("h-3 w-1 rounded-[1px]", slice.colorClass)} />
      </Section>
      {/* An unmapped MIME subtype can run long (MS-EXCEL.SHEET.MACROENABLED.12), so it clips with a tooltip instead of covering the counts. */}
      <Text
        maxLines={1}
        overflowTooltip
        font="secondary-body"
        color="text-03"
        data-testid="document-type-name"
      >
        {label(slice)}
      </Text>
    </Section>
  );
}

interface TypesTableProps {
  slices: DocumentTypeSlice[];
  hover: TypeHover;
  onFold: () => void;
}
/** The unfolded types on the card's columns, or two lines per type below 640 px; the fold button sits bottom right beside the last type. */
function TypesTable({ slices, hover, onFold }: TypesTableProps) {
  const t = useTranslations("admin.connector.statusCard");
  const format = useFormatter();
  const sizeParts = useSizeParts();
  function size(slice: DocumentTypeSlice): string {
    if (slice.sizeBytes === null) return "";
    const { value, unit } = sizeParts(slice.sizeBytes);
    return t("types.sizeValue", { value, unit });
  }
  function column(
    header: string,
    color: "text-04" | "text-03",
    value: (slice: DocumentTypeSlice) => string,
    className: string
  ) {
    return (
      <Section alignItems="end" gap={1} height="fit" className={className}>
        <Text font="secondary-body" color="text-03">
          {header}
        </Text>
        {slices.map((slice) => (
          <Section
            key={slice.key}
            alignItems="end"
            height="fit"
            {...typeCellProps(slice.key, hover, "min-h-4")}
          >
            <Text font="secondary-mono" color={color}>
              {value(slice)}
            </Text>
          </Section>
        ))}
      </Section>
    );
  }
  const foldLabel = t("actions.hideDetails");

  return (
    <Section height="fit" gap={0} className="@container relative">
      <Section
        height="fit"
        className="@max-[38.75rem]:hidden"
        data-testid="document-types-table"
      >
        <LineLayout
          variant="row"
          bSpansC
          a={
            <>
              <Divider paddingParallel={0} paddingPerpendicular={0} />
              <Text font="secondary-body" color="text-03">
                {t("types.header")}
              </Text>
              {slices.map((slice) => (
                <Section
                  key={slice.key}
                  alignItems="start"
                  height="fit"
                  {...typeCellProps(slice.key, hover)}
                >
                  <TypeName slice={slice} />
                </Section>
              ))}
            </>
          }
          b={
            <>
              <Divider paddingParallel={0} paddingPerpendicular={0} />
              <Section
                flexDirection="row"
                alignItems="start"
                gap={4}
                height="fit"
              >
                {column(
                  t("types.indexed"),
                  "text-04",
                  (slice) => format.number(slice.count),
                  "min-w-16 max-w-[6.5rem] flex-1"
                )}
                {column(t("types.size"), "text-03", size, "flex-1")}
              </Section>
            </>
          }
          c={null}
          d={null}
        />
      </Section>
      <Section
        alignItems="stretch"
        gap={1}
        height="fit"
        padding={2}
        className="hidden @max-[38.75rem]:flex"
        data-testid="document-types-list"
      >
        {slices.map((slice) => (
          <Section
            key={slice.key}
            alignItems="start"
            gap={0}
            width="auto"
            height="fit"
            data-testid="document-type-item"
            {...typeCellProps(slice.key, hover, "me-6")}
          >
            <TypeName slice={slice} />
            <Text font="secondary-mono" color="text-03">
              {slice.sizeBytes === null
                ? format.number(slice.count)
                : t("types.countWithSize", {
                    count: format.number(slice.count),
                    size: size(slice),
                  })}
            </Text>
          </Section>
        ))}
      </Section>
      <Section width="fit" height="fit" className="absolute bottom-1 end-1">
        <Button
          icon={SvgChevronUp}
          prominence="tertiary"
          size="md"
          tooltip={foldLabel}
          aria-label={foldLabel}
          aria-expanded
          onClick={onFold}
        />
      </Section>
    </Section>
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
  const tList = useTranslations("admin.indexing.list");
  const locale = useLocale();
  const liveDetail = useLiveRunDetail();
  const [stagesOpen, setStagesOpen] = useState(false);
  const typesRequest = useCCPairDocumentTypes(ccPair.id);
  const breakdown = typesRequest.data;
  // SWR keeps the last breakdown when a refresh fails, so the error alone decides: stale counts would read as current.
  const typesLoadFailed = typesRequest.error !== undefined;
  const [expanded, setExpanded] = useState(false);
  const [hoveredType, setHoveredType] = useState<string | null>(null);
  // Type colors stick per pair for the card's life, so a refresh that reorders the types never repaints them.
  const typeColors = useRef<TypeColorsByPair>(new Map());
  // A timed-out breakdown is unknown rather than empty, so it shows nothing, as a source without types does.
  const types =
    breakdown === undefined || breakdown.timed_out || typesLoadFailed
      ? []
      : breakdown.types;
  // Untyped documents would leave the breakdown short of the indexed count, so it neither unfolds nor sums a size.
  const fullyTyped = types.length > 0 && breakdown?.untyped_count === 0;
  const open = expanded && fullyTyped;
  const slices = useMemo(
    () =>
      open ? documentTypeSlices(typeColors.current, ccPair.id, types) : [],
    [open, ccPair.id, types]
  );
  // A hovered type that left the slices (a refresh moved it into Other) fires no leave, so only a shown type mutes the rest.
  const hovered = slices.some((slice) => slice.key === hoveredType)
    ? hoveredType
    : null;
  const hover: TypeHover = { hovered, onHover: setHoveredType };
  // Any fold drops the table under the pointer without a leave: the button, a timed-out or failed refresh, a new untyped document.
  useEffect(() => {
    if (!open) setHoveredType(null);
  }, [open]);
  const summary = typesLoadFailed ? (
    <TypesSummary typeCount={null} sizeBytes={null} />
  ) : (
    types.length > 0 && (
      <TypesSummary
        typeCount={types.length}
        sizeBytes={fullyTyped ? totalSize(types) : null}
      />
    )
  );
  const expandLabel = t("statusCard.actions.viewDetails");
  const hold = ccPair.indexing_hold;
  const paused = ccPair.status === ConnectorCredentialPairStatus.PAUSED;
  const indexing =
    !paused && hold === null && latestAttempt?.status === "in_progress";
  // A run that ends while its stages are open takes the popover with its trigger.
  if (stagesOpen && !indexing) setStagesOpen(false);
  const lastIndexed = t("statusCard.lastIndexed.value", {
    when: ago(ccPair.last_indexed, locale),
  });
  const deletionStartedAt = ccPair.latest_deletion_attempt?.started_at ?? null;
  // Scheduled and Deleting read the last index time while the API has no queue place or deletion start.
  function detail(): string {
    if (status.labelKey === "deleting" && deletionStartedAt !== null) {
      return t("statusCard.deletionStarted.value", {
        when: ago(deletionStartedAt, locale),
      });
    }
    if (paused) return lastIndexed;
    if (hold !== null) return t(`statusCard.hold.${hold.reason}`);
    if (status.labelKey === "scheduled" && ccPair.queue_position !== null) {
      return tList("detail.queued", { position: ccPair.queue_position });
    }
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
            bSpansC={open}
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
                      tooltip={tList("actions.viewErrors")}
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
              open ? (
                <Section alignItems="stretch" gap={1} height="fit">
                  <TypesBar slices={slices} hover={hover} />
                  <Section
                    flexDirection="row"
                    justifyContent="between"
                    alignItems="start"
                    height="fit"
                  >
                    <Section
                      alignItems="start"
                      gap={0}
                      width="fit"
                      height="fit"
                    >
                      <LineFigure
                        value={ccPair.num_docs_indexed}
                        label={t("statusCard.documents.indexedLabel")}
                      />
                    </Section>
                    {summary}
                  </Section>
                </Section>
              ) : (
                <CardFigure
                  value={ccPair.num_docs_indexed}
                  label={t("statusCard.documents.indexedLabel")}
                  holdsBarRow={fullyTyped}
                />
              )
            }
            c={
              !open &&
              summary && (
                <Section
                  alignItems="end"
                  height="fit"
                  className={cn("mt-6", !fullyTyped && "@max-[38.75rem]:mt-0")}
                >
                  {summary}
                </Section>
              )
            }
            d={
              // The panel button at the top, and the expand button 16 px under it at the line's foot.
              <Section
                alignItems="end"
                gap={4}
                width="fit"
                height="fit"
                className="mt-1"
              >
                <Section
                  width="fit"
                  height="fit"
                  className={panelButtonClassName}
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
                {fullyTyped && !open && (
                  <Button
                    icon={SvgChevronDown}
                    prominence="tertiary"
                    size="md"
                    tooltip={expandLabel}
                    aria-label={expandLabel}
                    aria-expanded={false}
                    onClick={() => setExpanded(true)}
                  />
                )}
              </Section>
            }
          />
          {open && (
            <TypesTable
              slices={slices}
              hover={hover}
              onFold={() => setExpanded(false)}
            />
          )}
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
