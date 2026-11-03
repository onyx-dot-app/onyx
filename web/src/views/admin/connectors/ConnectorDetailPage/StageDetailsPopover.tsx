"use client";

import { useFormatter, useTranslations } from "next-intl";
import {
  Button,
  Divider,
  IconTooltip,
  Popover,
  ShadowDiv,
  Text,
} from "@opal/components";
import { Section } from "@opal/layouts";
import type { ComponentProps, ReactNode } from "react";
import type { IconFunctionComponent, RichStr } from "@opal/types";
import { LineLoader } from "@opal/loaders";
import { SvgAlertTriangle, SvgStackLine } from "@opal/icons";
import { cn } from "@opal/utils";
import useIndexAttemptStageMetrics from "@/hooks/useIndexAttemptStageMetrics";
import type { IndexAttemptStage, IndexAttemptStageMetric } from "@/lib/types";
import {
  DetailsCloseButton,
  InlineDetailsCard,
  RunDetailsHint,
} from "@/views/admin/connectors/ConnectorDetailPage/InlineDetails";

// BATCH_TOTAL feeds the header; the bucket rows hold the other batch-level stages.
const SUMMARY_STAGE = "BATCH_TOTAL";

export const STAGE_BUCKETS = [
  "fetchSource",
  "batchPreProcessing",
  "chunking",
  "embedding",
  "vectorDbWrite",
  "postProcessing",
] as const;

export type StageBucket = (typeof STAGE_BUCKETS)[number];

// The row each stage counts toward, by its place in the pipeline. Attempt-level
// stages and the BATCH_TOTAL and BATCH_UNACCOUNTED aggregates get no row.
const STAGE_BUCKET = {
  CONNECTOR_VALIDATION: null,
  PERMISSION_VALIDATION: null,
  CHECKPOINT_LOAD: null,
  CONNECTOR_FETCH: "fetchSource",
  HIERARCHY_UPSERT: "fetchSource",
  DOC_BATCH_STORE: "batchPreProcessing",
  DOC_BATCH_ENQUEUE: "batchPreProcessing",
  QUEUE_WAIT: "batchPreProcessing",
  DOCPROCESSING_SETUP: "batchPreProcessing",
  BATCH_LOAD: "batchPreProcessing",
  DOC_DB_PREPARE: "batchPreProcessing",
  IMAGE_PROCESSING: "batchPreProcessing",
  CHUNKING: "chunking",
  CONTEXTUAL_RAG: "chunking",
  EMBEDDING: "embedding",
  EMBEDDING_RATE_LIMIT_WAIT: "embedding",
  EMBEDDING_PROVIDER_THROTTLE_WAIT: "embedding",
  DOC_LOCK_ACQUIRE_WAIT: "vectorDbWrite",
  ENRICHMENT_PREP: "vectorDbWrite",
  VECTOR_DB_WRITE: "vectorDbWrite",
  POST_INDEX_DB_UPDATE: "postProcessing",
  COORD_LOCK_ACQUIRE_WAIT: "postProcessing",
  COORDINATION_UPDATE: "postProcessing",
  FINALIZATION: "postProcessing",
  GC_COLLECT: "postProcessing",
  BATCH_UNACCOUNTED: null,
  BATCH_TOTAL: null,
} as const satisfies Record<IndexAttemptStage, StageBucket | null>;

// Timed inside EMBEDDING, so adding them to the bucket would count that time twice.
const INSIDE_EMBEDDING: ReadonlySet<IndexAttemptStage> = new Set([
  "EMBEDDING_RATE_LIMIT_WAIT",
  "EMBEDDING_PROVIDER_THROTTLE_WAIT",
]);

// The uneven marker is a muted hint, one step darker than IconTooltip's default stroke.
function UnevenIcon({
  className,
  ...props
}: ComponentProps<IconFunctionComponent>) {
  return (
    <SvgAlertTriangle {...props} className={cn(className, "stroke-text-02")} />
  );
}

const BUCKET_LABEL_KEYS = {
  fetchSource: "stageMetrics.buckets.fetchSource.label",
  batchPreProcessing: "stageMetrics.buckets.batchPreProcessing.label",
  chunking: "stageMetrics.buckets.chunking.label",
  embedding: "stageMetrics.buckets.embedding.label",
  vectorDbWrite: "stageMetrics.buckets.vectorDbWrite.label",
  postProcessing: "stageMetrics.buckets.postProcessing.label",
} as const satisfies Record<StageBucket, string>;

export interface BucketTiming {
  /** The most batches any one stage of the bucket saw. */
  batchCount: number;
  avgMs: number | null;
  stdDevMs: number | null;
  minMs: number | null;
  maxMs: number | null;
}

export interface BucketSummary {
  bucket: StageBucket;
  /** `undefined` when the attempt recorded none of the bucket's stages. */
  timing: BucketTiming | undefined;
}

function sumOrNull(values: (number | null)[]): number | null {
  const present = values.filter((value): value is number => value !== null);
  return present.length === 0
    ? null
    : present.reduce((total, value) => total + value, 0);
}

/**
 * One summary per bucket, in pipeline order. The average is the sum of the
 * stages' averages. The spread treats the stages as independent, and min and
 * max sum the stages' extremes, so they bound the bucket's slowest and fastest
 * batch rather than measure one.
 */
export function summarizeBuckets(
  metrics: IndexAttemptStageMetric[]
): BucketSummary[] {
  return STAGE_BUCKETS.map((bucket) => {
    const stages = metrics.filter(
      (metric) =>
        metric.scope === "BATCH_LEVEL" &&
        STAGE_BUCKET[metric.stage] === bucket &&
        !INSIDE_EMBEDDING.has(metric.stage)
    );
    if (stages.length === 0) return { bucket, timing: undefined };
    const variance = sumOrNull(
      stages.map(({ std_dev_duration_ms: sd }) =>
        sd === null ? null : sd * sd
      )
    );
    return {
      bucket,
      timing: {
        batchCount: Math.max(...stages.map((stage) => stage.event_count)),
        avgMs: sumOrNull(stages.map((stage) => stage.avg_duration_ms)),
        stdDevMs: variance === null ? null : Math.sqrt(variance),
        minMs: sumOrNull(stages.map((stage) => stage.min_duration_ms)),
        maxMs: sumOrNull(stages.map((stage) => stage.max_duration_ms)),
      },
    };
  });
}

/** A spread above the mean means batch times vary wildly. */
function isUneven({ avgMs, stdDevMs }: BucketTiming): boolean {
  return stdDevMs !== null && avgMs !== null && stdDevMs > avgMs;
}

/** What a stage figure shows when there is none. */
export const NONE = "--";

// Seconds with three decimals in the viewer's locale, as the mock prints every figure here.
const SECONDS_FORMAT = {
  minimumFractionDigits: 3,
  maximumFractionDigits: 3,
} as const;
export function formatSeconds(
  format: ReturnType<typeof useFormatter>,
  ms: number | null | undefined
): string {
  return ms == null ? NONE : `${format.number(ms / 1000, SECONDS_FORMAT)}s`;
}

function percent(ms: number, scale: number): string {
  return `${scale > 0 ? (ms / scale) * 100 : 0}%`;
}

/** The longest max across the rows, so the longest bar fills the track. */
export function barScale(buckets: BucketSummary[]): number {
  return Math.max(0, ...buckets.map(({ timing }) => timing?.maxMs ?? 0));
}

export interface StageDetailsTriggerProps {
  /** Whether its popover is open. The open trigger shows selected. */
  open?: boolean;
}
/** Opens the stage details of one attempt. Place it inside the Popover that holds the content. */
export function StageDetailsTrigger({
  open = false,
}: StageDetailsTriggerProps) {
  const t = useTranslations("admin.connector.runs");
  return (
    <Popover.Trigger asChild>
      <RunDetailsHint
        icon={SvgStackLine}
        label={t("actions.stages")}
        open={open}
      />
    </Popover.Trigger>
  );
}

interface AverageProps {
  avgMs: number | null | undefined;
  stdDevMs?: number | null;
}
/** The average in emphasis with its spread muted beside it. */
function Average({ avgMs, stdDevMs = null }: AverageProps) {
  const format = useFormatter();
  if (avgMs == null) {
    return (
      <Text font="secondary-mono" color="text-03">
        {NONE}
      </Text>
    );
  }
  return (
    <Section flexDirection="row" justifyContent="start" gap={1} height="fit">
      <Text font="secondary-mono-label" color="text-04">
        {formatSeconds(format, avgMs)}
      </Text>
      {stdDevMs !== null && (
        <>
          <Text font="secondary-mono" color="text-03">
            ±
          </Text>
          {/* Spreads right-align so their decimal points line up down the column. */}
          <Section
            flexDirection="row"
            justifyContent="end"
            width="auto"
            height="fit"
            className="min-w-0 flex-1"
          >
            <Text font="secondary-mono" color="text-03">
              {formatSeconds(format, stdDevMs)}
            </Text>
          </Section>
        </>
      )}
    </Section>
  );
}

interface ColumnTitleProps {
  children: string | RichStr;
}
function ColumnTitle({ children }: ColumnTitleProps) {
  return (
    <Text font="secondary-body" color="text-03">
      {children}
    </Text>
  );
}

interface DetailLineProps {
  name: ReactNode;
  batches: ReactNode;
  average: ReactNode;
  /** The min-to-max bar of a stage line. The header leaves the room empty. */
  bar?: ReactNode;
  max: ReactNode;
  action: ReactNode;
}
/**
 * One line of the stage card on the run line's columns: name and a 64 px batches column across A,
 * then from B's start the average, the bar, and a 60 px max column that ends on the counts edge, then D.
 * Below 640 px it wraps to A + D over the rest, as a run line does.
 */
function DetailLine({
  name,
  batches,
  average,
  bar,
  max,
  action,
}: DetailLineProps) {
  // A container query cannot measure its own element, so the parts query this wrapper.
  return (
    <div className="@container w-full">
      <Section
        flexDirection="row"
        justifyContent="start"
        alignItems="start"
        gap={0}
        height="fit"
        className="@max-[38.75rem]:flex-wrap"
      >
        {/* As wide as a run line's A: half of what the line's third, capped at 208 px, leaves. */}
        <Section
          flexDirection="row"
          alignItems="start"
          gap={4}
          padding={1}
          height="fit"
          className="min-w-0 shrink-0 basis-[calc((100%-min(33.333%,13rem))/2)] @max-[38.75rem]:order-1 @max-[38.75rem]:basis-[calc(100%-4rem)]"
        >
          <Section
            alignItems="start"
            gap={0}
            height="fit"
            className="ms-1 min-w-0 flex-1"
          >
            {name}
          </Section>
          <Section
            alignItems="end"
            gap={0}
            width={3.25}
            height="fit"
            className="shrink-0"
          >
            {batches}
          </Section>
        </Section>
        <Section
          flexDirection="row"
          justifyContent="start"
          gap={1}
          padding={1}
          height="fit"
          className="ms-1 min-w-0 flex-1 @max-[38.75rem]:order-3"
        >
          <Section
            alignItems="start"
            gap={0}
            width={7.75}
            height="fit"
            className="shrink-0"
          >
            {average}
          </Section>
          <Section
            alignItems="stretch"
            padding={1}
            height="fit"
            className="min-w-0 flex-1"
          >
            {bar}
          </Section>
          <Section
            alignItems="end"
            gap={0}
            width={3.75}
            height="fit"
            className="me-1 shrink-0"
          >
            {max}
          </Section>
        </Section>
        {/* No vertical padding, so a 24 px action keeps a stage line at 24 px. */}
        <Section
          flexDirection="row"
          justifyContent="end"
          alignItems="start"
          width={3.75}
          height="fit"
          className="me-1 shrink-0 @max-[38.75rem]:order-2"
        >
          {action}
        </Section>
      </Section>
    </div>
  );
}

interface StageBarProps {
  timing: BucketTiming;
  /** From `barScale`. */
  scale: number;
}
/** The bucket's min-to-max window on a track scaled to the slowest bucket, with its average marked. */
function StageBar({ timing, scale }: StageBarProps) {
  const min = timing.minMs ?? 0;
  const max = timing.maxMs ?? 0;
  return (
    <div className="relative h-1 w-full rounded-02 bg-background-tint-01">
      <div
        className="absolute top-0 h-1 rounded-02 bg-chart-category-blue-1-20"
        style={{
          insetInlineStart: percent(min, scale),
          width: `calc(${percent(max, scale)} - ${percent(min, scale)})`,
        }}
      />
      {timing.avgMs !== null && (
        <div
          className="absolute top-0 size-1 -ms-0.5 rounded-02 bg-chart-category-blue-1"
          style={{ insetInlineStart: percent(timing.avgMs, scale) }}
        />
      )}
    </div>
  );
}

interface BucketLineProps {
  summary: BucketSummary;
  /** From `barScale`. */
  scale: number;
}
/** One stage line: batch count, average, a min-to-max bar with the average marked, and max. D holds the uneven marker alone, since nothing ties an error to one stage. */
function BucketLine({ summary: { bucket, timing }, scale }: BucketLineProps) {
  const t = useTranslations("admin.connector");
  const format = useFormatter();
  return (
    <DetailLine
      name={
        <Text font="secondary-action" color="text-03">
          {t(BUCKET_LABEL_KEYS[bucket])}
        </Text>
      }
      batches={
        <Text font="secondary-mono" color="text-03">
          {timing === undefined ? NONE : format.number(timing.batchCount)}
        </Text>
      }
      average={<Average avgMs={timing?.avgMs} stdDevMs={timing?.stdDevMs} />}
      bar={timing !== undefined && <StageBar timing={timing} scale={scale} />}
      max={
        <Text font="secondary-mono" color="text-03">
          {formatSeconds(format, timing?.maxMs)}
        </Text>
      }
      action={
        timing !== undefined &&
        isUneven(timing) && (
          <IconTooltip
            icon={UnevenIcon}
            tooltip={t("stageDetails.uneven.tooltip")}
            aria-label={t("stageDetails.uneven.tooltip")}
          />
        )
      }
    />
  );
}

interface StageLinesProps {
  buckets: BucketSummary[];
  /** The run indexed nothing, so only the stages that ran are listed, then a note that the rest were canceled. */
  noDocs: boolean;
}
function StageLines({ buckets, noDocs }: StageLinesProps) {
  const t = useTranslations("admin.connector");
  const ran = buckets.filter(({ timing }) => timing !== undefined);
  if (ran.length === 0 && !noDocs) {
    return (
      <Section padding={1} height="fit">
        <Text font="secondary-body" color="text-03">
          {t("stageMetrics.perBatch.empty")}
        </Text>
      </Section>
    );
  }
  const scale = barScale(buckets);
  return (
    <ShadowDiv>
      <Section alignItems="stretch" gap={1} height="fit">
        {(noDocs ? ran : buckets).map((summary) => (
          <BucketLine key={summary.bucket} summary={summary} scale={scale} />
        ))}
        {/* The stages that never ran have no figures, so the note stands alone rather than folding them away. */}
        {noDocs && ran.length < buckets.length && (
          <Divider title={t("stageDetails.laterCanceled")} />
        )}
      </Section>
    </ShadowDiv>
  );
}

interface StageDetailsProps {
  indexAttemptId: number;
  noDocs: boolean;
  /** Closes an inline card. Unset, the close button closes the enclosing Popover. */
  onClose?: () => void;
}

/** How long each pipeline step took per batch of one index attempt, on the run line's columns. The header carries the attempt's totals under each column title. */
function StageDetails({ indexAttemptId, noDocs, onClose }: StageDetailsProps) {
  const t = useTranslations("admin.connector");
  const format = useFormatter();
  const { data, error, mutate } = useIndexAttemptStageMetrics(indexAttemptId);
  const stages = data?.stages ?? [];
  const total = stages.find((stage) => stage.stage === SUMMARY_STAGE);
  const buckets = summarizeBuckets(stages);

  function lines(): ReactNode {
    if (error !== undefined) {
      return (
        <Section
          flexDirection="row"
          justifyContent="between"
          gap={1}
          padding={1}
          height="fit"
        >
          <Text font="secondary-body" color="text-03">
            {t("stageMetrics.loadError.title")}
          </Text>
          <Button prominence="internal" size="sm" onClick={() => void mutate()}>
            {t("stageDetails.retry")}
          </Button>
        </Section>
      );
    }
    if (data === undefined) {
      return (
        <Section padding={1} height="fit">
          <LineLoader lines={3} />
        </Section>
      );
    }
    // A run that indexed nothing and recorded no stage shows its header alone.
    if (noDocs && buckets.every(({ timing }) => timing === undefined)) {
      return null;
    }
    return <StageLines buckets={buckets} noDocs={noDocs} />;
  }
  const body = lines();

  return (
    <Section
      alignItems="stretch"
      gap={1}
      height="auto"
      className="my-1 min-h-0"
    >
      <DetailLine
        name={
          <>
            <ColumnTitle>{t("stageDetails.heading.top")}</ColumnTitle>
            <ColumnTitle>{t("stageDetails.heading.bottom")}</ColumnTitle>
          </>
        }
        batches={
          <>
            <ColumnTitle>{t("stageDetails.calls")}</ColumnTitle>
            <Text font="secondary-mono-label" color="text-04">
              {noDocs || total === undefined
                ? NONE
                : format.number(total.event_count)}
            </Text>
          </>
        }
        average={
          <>
            <ColumnTitle>{t("stageDetails.averageTime")}</ColumnTitle>
            {noDocs ? (
              // One line running into the empty bar room, as the design draws it.
              <Text
                font="secondary-action"
                color="text-04"
                wordWrap="whitespace-nowrap"
              >
                {t("stageDetails.noDocs")}
              </Text>
            ) : (
              <Average
                avgMs={total?.avg_duration_ms}
                stdDevMs={total?.std_dev_duration_ms}
              />
            )}
          </>
        }
        max={
          <>
            <ColumnTitle>{t("stageDetails.maxTime")}</ColumnTitle>
            <Text font="secondary-mono" color="text-03">
              {noDocs ? NONE : formatSeconds(format, total?.max_duration_ms)}
            </Text>
          </>
        }
        action={
          <DetailsCloseButton
            label={t("stageDetails.close")}
            onClose={onClose}
          />
        }
      />
      {body !== null && (
        <>
          {/* An 8 px band around the 1 px line. */}
          <Section height={0.5}>
            <Divider paddingParallel={1} paddingPerpendicular={0} />
          </Section>
          {body}
        </>
      )}
    </Section>
  );
}

export interface StageDetailsPopoverContentProps {
  indexAttemptId: number;
}

/** Stage details for one attempt, as wide as the caller's Popover.Anchor.
 *  Radix mounts the content only while open, so nothing is fetched until then. */
export default function StageDetailsPopoverContent({
  indexAttemptId,
}: StageDetailsPopoverContentProps) {
  const t = useTranslations("admin.connector");
  return (
    // The negative offset tucks the popover under the card's bottom padding, as in the mock.
    <Popover.Content
      width="trigger"
      align="start"
      sideOffset={-8}
      aria-label={t("stageDetails.title")}
    >
      <Section
        alignItems="stretch"
        padding={1}
        height="auto"
        className="min-h-0"
      >
        <StageDetails indexAttemptId={indexAttemptId} noDocs={false} />
      </Section>
    </Popover.Content>
  );
}

export interface StageDetailsCardProps {
  indexAttemptId: number;
  /** The run finished without indexing a document. */
  noDocs: boolean;
  onClose: () => void;
}

/** Stage details for one attempt in a card directly under its run line. Fetches on mount, so mount it only while open. */
export function StageDetailsCard({
  indexAttemptId,
  noDocs,
  onClose,
}: StageDetailsCardProps) {
  const t = useTranslations("admin.connector");
  return (
    <InlineDetailsCard label={t("stageDetails.title")} onClose={onClose}>
      <StageDetails
        indexAttemptId={indexAttemptId}
        noDocs={noDocs}
        onClose={onClose}
      />
    </InlineDetailsCard>
  );
}
