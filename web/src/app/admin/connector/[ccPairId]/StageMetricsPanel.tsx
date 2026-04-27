"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import { Button, Text } from "@opal/components";
import { SvgQuestionMarkSmall } from "@opal/icons";
import { Callout } from "@/components/ui/callout";
import {
  Table,
  TableHead,
  TableRow,
  TableBody,
  TableCell,
  TableHeader,
} from "@/components/ui/table";
import * as GeneralLayouts from "@/layouts/general-layouts";
import { errorHandlingFetcher, skipRetryOnAuthError } from "@/lib/fetcher";
import { formatDurationMs } from "@/lib/time";
import {
  INDEX_ATTEMPT_STAGES,
  IndexAttemptStage,
  IndexAttemptStageMetric,
  IndexAttemptStageMetricsResponse,
} from "@/lib/types";
import { cn } from "@opal/utils";

// Human-readable label per stage. Explicit (rather than auto-cased) so that
// acronyms like DB / RAG render correctly.
const STAGE_LABELS: Record<IndexAttemptStage, string> = {
  CONNECTOR_VALIDATION: "Connector validation",
  PERMISSION_VALIDATION: "Permission validation",
  CHECKPOINT_LOAD: "Checkpoint load",
  CONNECTOR_FETCH: "Connector fetch",
  HIERARCHY_UPSERT: "Hierarchy upsert",
  DOC_BATCH_STORE: "Doc batch store",
  DOC_BATCH_ENQUEUE: "Doc batch enqueue",
  QUEUE_WAIT: "Queue wait",
  DOCPROCESSING_SETUP: "Docprocessing setup",
  BATCH_LOAD: "Batch load",
  DOC_DB_PREPARE: "Doc DB prepare",
  IMAGE_PROCESSING: "Image processing",
  CHUNKING: "Chunking",
  CONTEXTUAL_RAG: "Contextual RAG",
  EMBEDDING: "Embedding",
  VECTOR_DB_WRITE: "Vector DB write",
  POST_INDEX_DB_UPDATE: "Post-index DB update",
  COORDINATION_UPDATE: "Coordination update",
  BATCH_TOTAL: "Batch total",
};

// Short explainer per stage, shown in a tooltip next to each row in the
// per-batch table so admins can interpret the timings without leaving the
// modal.
const STAGE_DESCRIPTIONS: Record<IndexAttemptStage, string> = {
  CONNECTOR_VALIDATION:
    "Validates that the connector is configured correctly and reachable before fetching begins.",
  PERMISSION_VALIDATION:
    "Verifies the credential has the permissions needed to read documents from the source.",
  CHECKPOINT_LOAD:
    "Loads any prior checkpoint so a resumed attempt can pick up where the last one left off.",
  CONNECTOR_FETCH:
    "Time spent calling the upstream source to retrieve a batch of raw documents.",
  HIERARCHY_UPSERT:
    "Records hierarchy and metadata relationships (folders, parents, etc.) for the batch in Postgres.",
  DOC_BATCH_STORE:
    "Persists the fetched batch to the file store so the docprocessing worker can consume it asynchronously.",
  DOC_BATCH_ENQUEUE:
    "Submits a docprocessing task for the batch onto the Celery queue.",
  QUEUE_WAIT:
    "Time the docprocessing task spent waiting in the Celery queue before a worker picked it up.",
  DOCPROCESSING_SETUP:
    "One-time setup the docprocessing worker performs before processing batches (DB session, embedder, etc.).",
  BATCH_LOAD:
    "Reads the batch back from the file store inside the docprocessing worker.",
  DOC_DB_PREPARE:
    "Cleans, dedupes, and prepares documents for indexing — includes the DB lookups against existing document state.",
  IMAGE_PROCESSING:
    "Extracts and processes images embedded in document sections.",
  CHUNKING: "Splits documents into chunks sized for the embedding model.",
  CONTEXTUAL_RAG:
    "Optional LLM call that adds short contextual summaries to each chunk to improve retrieval quality.",
  EMBEDDING: "Calls the embedding model to produce vectors for each chunk.",
  VECTOR_DB_WRITE: "Writes the embedded chunks and their metadata to Vespa.",
  POST_INDEX_DB_UPDATE:
    "Updates Postgres with final document state after indexing (last-indexed timestamps, hashes, etc.).",
  COORDINATION_UPDATE:
    "Bookkeeping updates after a batch — progress counters, checkpoint advances, and similar.",
  BATCH_TOTAL:
    "Total wall-clock time elapsed processing a single batch end-to-end.",
};

// Distinct background classes for the per-row average-time bar. Cycled by
// stage's pipeline-order index so the same stage gets the same color in both
// the bar and the table swatch regardless of the active sort mode.
const STAGE_BAR_COLORS = [
  "bg-theme-blue-05",
  "bg-theme-green-05",
  "bg-theme-orange-05",
  "bg-theme-purple-05",
  "bg-theme-cyan-05",
  "bg-theme-red-05",
  "bg-theme-yellow-05",
  "bg-theme-primary-05",
] as const;

const PIPELINE_ORDER: Record<IndexAttemptStage, number> = Object.fromEntries(
  INDEX_ATTEMPT_STAGES.map((stage, idx) => [stage, idx])
) as Record<IndexAttemptStage, number>;

type SortMode = "pipeline" | "time-taken";

interface StageMetricsPanelProps {
  indexAttemptId: number;
}

export default function StageMetricsPanel({
  indexAttemptId,
}: StageMetricsPanelProps) {
  const [sortMode, setSortMode] = useState<SortMode>("pipeline");

  const { data, error, isLoading } = useSWR<IndexAttemptStageMetricsResponse>(
    `/api/manage/admin/index-attempt/${indexAttemptId}/stage-metrics`,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      onErrorRetry: skipRetryOnAuthError,
    }
  );

  const { batchTotal, perBatchStages, attemptStages } = useMemo(() => {
    const stages = data?.stages ?? [];
    const total = stages.find((s) => s.stage === "BATCH_TOTAL") ?? null;
    const perBatch = stages.filter(
      (s) => s.scope === "BATCH_LEVEL" && s.stage !== "BATCH_TOTAL"
    );
    const attempt = stages.filter((s) => s.scope === "ATTEMPT_LEVEL");
    return {
      batchTotal: total,
      perBatchStages: perBatch,
      attemptStages: attempt,
    };
  }, [data]);

  if (isLoading) {
    return (
      <Text font="secondary-body" color="text-03">
        Loading stage metrics…
      </Text>
    );
  }

  if (error) {
    return (
      <Callout title="Failed to load stage metrics" type="warning">
        Stage timing data could not be loaded for this attempt. The pipeline
        runs even when metric recording is unavailable, so this does not
        indicate a problem with the indexing run itself.
      </Callout>
    );
  }

  if (!data || data.stages.length === 0) {
    return (
      <Text font="secondary-body" color="text-03">
        No stage timing data has been recorded for this attempt yet. Older
        attempts that ran before stage instrumentation was deployed will not
        have metrics.
      </Text>
    );
  }

  return (
    <GeneralLayouts.Section
      alignItems="start"
      height="fit"
      width="full"
      gap={0.75}
    >
      <BatchTotalHeader batchTotal={batchTotal} />
      <PerBatchSection
        perBatchStages={perBatchStages}
        sortMode={sortMode}
        onSortModeChange={setSortMode}
      />
      {attemptStages.length > 0 && (
        <AttemptOverhead attemptStages={attemptStages} />
      )}
    </GeneralLayouts.Section>
  );
}

interface BatchTotalHeaderProps {
  batchTotal: IndexAttemptStageMetric | null;
}

function BatchTotalHeader({ batchTotal }: BatchTotalHeaderProps) {
  if (!batchTotal || batchTotal.event_count === 0) {
    return (
      <Text font="main-ui-action" color="text-04">
        No completed batches yet
      </Text>
    );
  }

  const avg = batchTotal.avg_duration_ms;
  const std = batchTotal.std_dev_duration_ms;
  const avgLabel =
    avg !== null
      ? std !== null
        ? `${formatDurationMs(avg)} ± ${formatDurationMs(std)}`
        : formatDurationMs(avg)
      : "—";

  return (
    <Text font="main-ui-action" color="text-05">
      {`Average batch: ${avgLabel}, ${batchTotal.event_count} ${
        batchTotal.event_count === 1 ? "batch" : "batches"
      } — distribution shown below.`}
    </Text>
  );
}

interface PerBatchSectionProps {
  perBatchStages: IndexAttemptStageMetric[];
  sortMode: SortMode;
  onSortModeChange: (mode: SortMode) => void;
}

function PerBatchSection({
  perBatchStages,
  sortMode,
  onSortModeChange,
}: PerBatchSectionProps) {
  if (perBatchStages.length === 0) {
    return (
      <Text font="secondary-body" color="text-03">
        No per-batch stage data recorded.
      </Text>
    );
  }
  return (
    <GeneralLayouts.Section
      alignItems="start"
      height="fit"
      width="full"
      gap={0.75}
    >
      <SortToggle sortMode={sortMode} onChange={onSortModeChange} />
      <PerBatchTable perBatchStages={perBatchStages} sortMode={sortMode} />
    </GeneralLayouts.Section>
  );
}

interface SortToggleProps {
  sortMode: SortMode;
  onChange: (mode: SortMode) => void;
}

function SortToggle({ sortMode, onChange }: SortToggleProps) {
  return (
    <GeneralLayouts.Section
      flexDirection="row"
      justifyContent="start"
      alignItems="center"
      width="fit"
      height="fit"
      gap={0.5}
    >
      <Text font="secondary-body" color="text-03">
        Sort:
      </Text>
      <Button
        prominence={sortMode === "pipeline" ? "secondary" : "tertiary"}
        size="sm"
        onClick={() => onChange("pipeline")}
      >
        Pipeline order
      </Button>
      <Button
        prominence={sortMode === "time-taken" ? "secondary" : "tertiary"}
        size="sm"
        onClick={() => onChange("time-taken")}
      >
        Time taken
      </Button>
    </GeneralLayouts.Section>
  );
}

// Sort per-batch stages according to the current sort mode. Pipeline order is
// the canonical enum declaration order; time-taken sorts descending by
// total duration so the long pole sits first.
function sortPerBatchStages(
  stages: IndexAttemptStageMetric[],
  sortMode: SortMode
): IndexAttemptStageMetric[] {
  const sorted = [...stages];
  if (sortMode === "pipeline") {
    sorted.sort(
      (a, b) => (PIPELINE_ORDER[a.stage] ?? 0) - (PIPELINE_ORDER[b.stage] ?? 0)
    );
  } else {
    sorted.sort((a, b) => b.total_duration_ms - a.total_duration_ms);
  }
  return sorted;
}

function colorClassForStage(stage: IndexAttemptStage): string {
  const idx = PIPELINE_ORDER[stage] ?? 0;
  return STAGE_BAR_COLORS[idx % STAGE_BAR_COLORS.length]!;
}

interface PerBatchTableProps {
  perBatchStages: IndexAttemptStageMetric[];
  sortMode: SortMode;
}

function PerBatchTable({ perBatchStages, sortMode }: PerBatchTableProps) {
  const sorted = useMemo(
    () => sortPerBatchStages(perBatchStages, sortMode),
    [perBatchStages, sortMode]
  );

  // Used to scale the per-row average-time bar. Falls back to 0 when no
  // stage has an average yet, in which case rows render no bar at all.
  const maxAvgMs = useMemo(
    () =>
      sorted.reduce(
        (acc, s) =>
          s.avg_duration_ms !== null ? Math.max(acc, s.avg_duration_ms) : acc,
        0
      ),
    [sorted]
  );

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Stage</TableHead>
          <TableHead>Avg time</TableHead>
          <TableHead className="text-right">Total time</TableHead>
          <TableHead className="text-right">Calls</TableHead>
          <TableHead className="text-right">Min</TableHead>
          <TableHead className="text-right">Max</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {sorted.map((stage) => (
          <PerBatchTableRow
            key={stage.stage}
            stage={stage}
            maxAvgMs={maxAvgMs}
          />
        ))}
      </TableBody>
    </Table>
  );
}

interface PerBatchTableRowProps {
  stage: IndexAttemptStageMetric;
  maxAvgMs: number;
}

function PerBatchTableRow({ stage, maxAvgMs }: PerBatchTableRowProps) {
  const avg = stage.avg_duration_ms;
  const std = stage.std_dev_duration_ms;
  const avgLabel =
    avg !== null
      ? std !== null
        ? `${formatDurationMs(avg)} ± ${formatDurationMs(std)}`
        : formatDurationMs(avg)
      : "—";
  const avgPct = avg !== null && maxAvgMs > 0 ? (avg / maxAvgMs) * 100 : 0;

  return (
    <TableRow>
      <TableCell>
        <GeneralLayouts.Section
          flexDirection="row"
          justifyContent="start"
          alignItems="center"
          width="fit"
          height="fit"
          gap={0.5}
        >
          {/* Inline color swatch: a color-only marker doesn't fit any
              layout primitive, and Tailwind handles the styling fully. */}
          <span
            aria-hidden="true"
            className={cn(
              "inline-block h-2 w-2 rounded-full shrink-0",
              colorClassForStage(stage.stage)
            )}
          />
          <Text font="secondary-body" color="text-05">
            {STAGE_LABELS[stage.stage]}
          </Text>
          <Button
            icon={SvgQuestionMarkSmall}
            prominence="tertiary"
            size="sm"
            tooltip={STAGE_DESCRIPTIONS[stage.stage]}
          />
        </GeneralLayouts.Section>
      </TableCell>
      <TableCell>
        <GeneralLayouts.Section
          alignItems="start"
          justifyContent="center"
          width="full"
          height="fit"
          gap={0.25}
        >
          <Text font="secondary-body" color="text-05">
            {avgLabel}
          </Text>
          {avgPct > 0 && (
            // Track + filled bar. Inline width is unavoidable since the bar
            // length is derived from a runtime ratio Tailwind can't express.
            <div
              aria-hidden="true"
              className="w-full h-1 rounded-full bg-background-tint-01 overflow-hidden"
            >
              <div
                className={cn(
                  "h-full rounded-full",
                  colorClassForStage(stage.stage)
                )}
                style={{ width: `${avgPct}%` }}
              />
            </div>
          )}
        </GeneralLayouts.Section>
      </TableCell>
      <TableCell className="text-right">
        {formatDurationMs(stage.total_duration_ms)}
      </TableCell>
      <TableCell className="text-right">{stage.event_count}</TableCell>
      <TableCell className="text-right">
        {stage.min_duration_ms !== null
          ? formatDurationMs(stage.min_duration_ms)
          : "—"}
      </TableCell>
      <TableCell className="text-right">
        {stage.max_duration_ms !== null
          ? formatDurationMs(stage.max_duration_ms)
          : "—"}
      </TableCell>
    </TableRow>
  );
}

interface AttemptOverheadProps {
  attemptStages: IndexAttemptStageMetric[];
}

// Per-attempt setup stages — one event each, no std dev, no chart. Rendered
// as a small disclosure beneath the main view to avoid overwhelming the
// admin while still surfacing one-off setup regressions.
function AttemptOverhead({ attemptStages }: AttemptOverheadProps) {
  const [open, setOpen] = useState(false);
  const sorted = useMemo(() => {
    const copy = [...attemptStages];
    copy.sort(
      (a, b) => (PIPELINE_ORDER[a.stage] ?? 0) - (PIPELINE_ORDER[b.stage] ?? 0)
    );
    return copy;
  }, [attemptStages]);

  return (
    <GeneralLayouts.Section
      alignItems="start"
      height="fit"
      width="full"
      gap={0.25}
    >
      <Button
        prominence="tertiary"
        size="sm"
        onClick={() => setOpen((o) => !o)}
      >
        {open ? "Hide attempt overhead" : "Show attempt overhead"}
      </Button>
      {open && <AttemptOverheadList stages={sorted} />}
    </GeneralLayouts.Section>
  );
}

interface AttemptOverheadListProps {
  stages: IndexAttemptStageMetric[];
}

function AttemptOverheadList({ stages }: AttemptOverheadListProps) {
  return (
    <GeneralLayouts.Section
      alignItems="stretch"
      height="fit"
      width="full"
      gap={0.125}
    >
      {stages.map((stage) => (
        <AttemptOverheadRow key={stage.stage} stage={stage} />
      ))}
    </GeneralLayouts.Section>
  );
}

interface AttemptOverheadRowProps {
  stage: IndexAttemptStageMetric;
}

function AttemptOverheadRow({ stage }: AttemptOverheadRowProps) {
  return (
    <GeneralLayouts.Section
      flexDirection="row"
      justifyContent="between"
      alignItems="center"
      width="full"
      height="fit"
      gap={1}
    >
      <Text font="secondary-body" color="text-04">
        {STAGE_LABELS[stage.stage]}
      </Text>
      <Text font="secondary-body" color="text-03">
        {formatDurationMs(stage.total_duration_ms)}
      </Text>
    </GeneralLayouts.Section>
  );
}
