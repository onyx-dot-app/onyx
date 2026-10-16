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
import type { RichStr } from "@opal/types";
import { LineLoader } from "@opal/loaders";
import { SvgAlertTriangle, SvgStackLine, SvgX } from "@opal/icons";
import useIndexAttemptStageMetrics from "@/hooks/useIndexAttemptStageMetrics";
import type { IndexAttemptStage, IndexAttemptStageMetric } from "@/lib/types";

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

// The row each stage counts toward. Attempt-level stages and the BATCH_TOTAL
// and BATCH_UNACCOUNTED aggregates get no row.
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

/** One summary per bucket, in pipeline order. Times are the sums of the stages' times; the spread is the root of the summed variances. */
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

// Column widths from the mock, in rem: the stage name, the batch count, the
// average with its spread, the bar and the max. The actions take the rest.
const NAME_WIDTH = 9.25;
const BATCHES_WIDTH = 3.5;
const AVERAGE_WIDTH = 8.5;
const BAR_WIDTH = 5.75;
const MAX_WIDTH = 4;
// Seconds with three decimals, as the mock prints every figure here.
export function formatSeconds(ms: number | null | undefined): string {
  return ms == null ? "-" : `${(ms / 1000).toFixed(3)}s`;
}

function percent(ms: number, scale: number): string {
  return `${scale > 0 ? (Math.min(ms, scale) / scale) * 100 : 0}%`;
}

/**
 * The longest average plus one spread across the rows. One very long max
 * would otherwise squash every other bar to a dot, so longer bars get clipped.
 */
export function barScale(buckets: BucketSummary[]): number {
  const timings = buckets.flatMap(({ timing }) => (timing ? [timing] : []));
  const scale = Math.max(
    0,
    ...timings.map(({ avgMs, stdDevMs }) =>
      avgMs === null ? 0 : avgMs + (stdDevMs ?? 0)
    )
  );
  return scale > 0
    ? scale
    : Math.max(0, ...timings.map(({ maxMs }) => maxMs ?? 0));
}

/** Opens the stage details of one attempt. Place it inside the Popover that holds the content. */
export function StageDetailsTrigger() {
  const t = useTranslations("admin.connector.runs");
  return (
    <Popover.Trigger asChild>
      <Button
        icon={SvgStackLine}
        prominence="tertiary"
        size="xs"
        tooltip={t("actions.stages")}
        aria-label={t("actions.stages")}
      />
    </Popover.Trigger>
  );
}

interface CellProps {
  width: number;
  align?: "start" | "end";
  children: React.ReactNode;
}
/** One fixed-width column of a row, padded as the mock's cells are. */
function Cell({ width, align = "start", children }: CellProps) {
  return (
    <Section
      alignItems={align}
      justifyContent="start"
      gap={1}
      padding={1}
      width={width}
      height="fit"
      className="shrink-0"
    >
      {children}
    </Section>
  );
}

interface AverageProps {
  avgMs: number | null | undefined;
  stdDevMs?: number | null;
}
/** The average in emphasis with its spread muted beside it. */
function Average({ avgMs, stdDevMs = null }: AverageProps) {
  if (avgMs == null) {
    return (
      <Text font="secondary-mono" color="text-03">
        -
      </Text>
    );
  }
  return (
    <Section
      flexDirection="row"
      alignItems="center"
      justifyContent="start"
      gap={1}
      width="fit"
      height="fit"
    >
      <Text font="secondary-mono-label" color="text-04">
        {formatSeconds(avgMs)}
      </Text>
      {stdDevMs !== null && (
        <Text font="secondary-mono" color="text-03">
          {`± ${formatSeconds(stdDevMs)}`}
        </Text>
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

interface BucketRowProps {
  summary: BucketSummary;
  /** From `barScale`; bars running past it are clipped. */
  scale: number;
}
/** One row: batch count, average, a min-to-max bar with the average marked, and max. */
function BucketRow({ summary: { bucket, timing }, scale }: BucketRowProps) {
  const t = useTranslations("admin.connector");
  const format = useFormatter();
  const min = timing?.minMs ?? 0;
  const max = timing?.maxMs ?? 0;
  const clipped = max > scale;

  return (
    <Section
      flexDirection="row"
      alignItems="center"
      justifyContent="start"
      gap={1}
      height="fit"
    >
      <Cell width={NAME_WIDTH}>
        <Text font="secondary-action" color="text-03">
          {t(BUCKET_LABEL_KEYS[bucket])}
        </Text>
      </Cell>
      <Cell width={BATCHES_WIDTH} align="end">
        <Text font="secondary-mono" color="text-03">
          {timing === undefined ? "-" : format.number(timing.batchCount)}
        </Text>
      </Cell>
      <Cell width={AVERAGE_WIDTH}>
        <Average avgMs={timing?.avgMs} stdDevMs={timing?.stdDevMs} />
      </Cell>
      <Cell width={BAR_WIDTH}>
        {timing === undefined ? (
          <Text font="secondary-mono" color="text-03">
            -
          </Text>
        ) : (
          <div className="relative my-1.5 h-1 w-full rounded-sm bg-background-tint-01">
            <div
              className="absolute top-0 h-1 rounded-sm bg-theme-blue-02"
              style={{
                insetInlineStart: percent(min, scale),
                width: `calc(${percent(max, scale)} - ${percent(min, scale)})`,
              }}
            />
            {clipped && (
              <div
                role="img"
                aria-label={t("stageDetails.clipped.label")}
                title={t("stageDetails.clipped.label")}
                className="absolute -top-1 end-0 h-3 w-0.5 rounded-sm bg-theme-blue-05"
              />
            )}
            {timing.avgMs !== null && (
              <div
                className="absolute top-0 h-1 w-1 -ms-0.5 rounded-sm bg-theme-blue-05"
                style={{
                  insetInlineStart: percent(timing.avgMs, scale),
                }}
              />
            )}
          </div>
        )}
      </Cell>
      <Cell width={MAX_WIDTH} align="end">
        <Text font="secondary-mono" color="text-03">
          {formatSeconds(timing?.maxMs)}
        </Text>
      </Cell>
      <Section
        flexDirection="row"
        alignItems="center"
        justifyContent="end"
        width="auto"
        height="fit"
        className="min-w-0 flex-1"
      >
        {timing !== undefined && isUneven(timing) && (
          <IconTooltip
            icon={SvgAlertTriangle}
            tooltip={t("stageDetails.uneven.tooltip")}
            aria-label={t("stageDetails.uneven.tooltip")}
          />
        )}
      </Section>
    </Section>
  );
}

interface StageRowsProps {
  stages: IndexAttemptStageMetric[];
  loaded: boolean;
  failed: boolean;
}
function StageRows({ stages, loaded, failed }: StageRowsProps) {
  const t = useTranslations("admin.connector");
  if (failed) {
    return (
      <Section padding={1} height="fit">
        <Text font="secondary-body" color="text-03">
          {t("stageMetrics.loadError.title")}
        </Text>
      </Section>
    );
  }
  if (!loaded) {
    return (
      <Section padding={1} height="fit">
        <LineLoader lines={3} />
      </Section>
    );
  }
  const buckets = summarizeBuckets(stages);
  if (buckets.every(({ timing }) => timing === undefined)) {
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
      {buckets.map((summary) => (
        <BucketRow key={summary.bucket} summary={summary} scale={scale} />
      ))}
    </ShadowDiv>
  );
}

interface StageDetailsBodyProps {
  indexAttemptId: number;
}

/** How long each pipeline step took per batch of one index attempt. The header carries the attempt's totals under each column title. */
function StageDetailsBody({ indexAttemptId }: StageDetailsBodyProps) {
  const t = useTranslations("admin.connector");
  const format = useFormatter();
  const { data, error } = useIndexAttemptStageMetrics(indexAttemptId);
  const stages = data?.stages ?? [];
  const total = stages.find((stage) => stage.stage === SUMMARY_STAGE);

  return (
    <Section
      alignItems="stretch"
      gap={1}
      padding={1}
      height="auto"
      className="min-h-0"
    >
      <Section
        flexDirection="row"
        alignItems="start"
        justifyContent="start"
        gap={1}
        height="fit"
        className="shrink-0"
      >
        <Cell width={NAME_WIDTH}>
          <ColumnTitle>{t("stageDetails.title")}</ColumnTitle>
        </Cell>
        <Cell width={BATCHES_WIDTH} align="end">
          <ColumnTitle>{t("stageDetails.calls")}</ColumnTitle>
          <Text font="secondary-mono-label" color="text-04">
            {total === undefined ? "-" : format.number(total.event_count)}
          </Text>
        </Cell>
        <Cell width={AVERAGE_WIDTH}>
          <ColumnTitle>{t("stageDetails.averageTime")}</ColumnTitle>
          <Average
            avgMs={total?.avg_duration_ms}
            stdDevMs={total?.std_dev_duration_ms}
          />
        </Cell>
        <Cell width={BAR_WIDTH + MAX_WIDTH} align="end">
          <ColumnTitle>{t("stageDetails.maxTime")}</ColumnTitle>
          <Text font="secondary-mono" color="text-03">
            {formatSeconds(total?.max_duration_ms)}
          </Text>
        </Cell>
        <Section
          flexDirection="row"
          alignItems="start"
          justifyContent="end"
          width="auto"
          height="fit"
          className="min-w-0 flex-1"
        >
          <Popover.Close asChild>
            <Button
              icon={SvgX}
              prominence="tertiary"
              size="xs"
              aria-label={t("stageDetails.close")}
            />
          </Popover.Close>
        </Section>
      </Section>
      <Divider paddingParallel={1} paddingPerpendicular={1} />
      <StageRows
        stages={stages}
        loaded={data !== undefined}
        failed={error !== undefined}
      />
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
      <StageDetailsBody indexAttemptId={indexAttemptId} />
    </Popover.Content>
  );
}
