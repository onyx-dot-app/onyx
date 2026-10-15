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
import { formatDurationMs } from "@opal/time";
import { SvgInfo, SvgStackLine, SvgX } from "@opal/icons";
import useIndexAttemptStageMetrics from "@/hooks/useIndexAttemptStageMetrics";
import type { IndexAttemptStageMetric } from "@/lib/types";
import {
  PIPELINE_ORDER,
  STAGE_LABEL_KEYS,
} from "@/lib/connectors/stageMetrics/constants";

// BATCH_TOTAL feeds the header. BATCH_UNACCOUNTED is a computed residual, not a stage, so neither gets a row.
const SUMMARY_STAGE = "BATCH_TOTAL";
const HIDDEN_STAGES = new Set<IndexAttemptStageMetric["stage"]>([
  SUMMARY_STAGE,
  "BATCH_UNACCOUNTED",
]);

// Column widths from the mock, in rem: the stage name, the batch count, the
// average with its spread, the bar and the max. The actions take the rest.
const NAME_WIDTH = 9.25;
const BATCHES_WIDTH = 3.5;
const AVERAGE_WIDTH = 8.5;
const BAR_WIDTH = 5.75;
const MAX_WIDTH = 4;

function formatMs(ms: number | null | undefined): string {
  return ms == null ? "-" : formatDurationMs(ms);
}

function percent(ms: number, scale: number): string {
  return `${scale > 0 ? (ms / scale) * 100 : 0}%`;
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
  stage: IndexAttemptStageMetric | undefined;
}
/** The average in emphasis with its spread muted beside it. */
function Average({ stage }: AverageProps) {
  if (stage?.avg_duration_ms == null) {
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
        {formatDurationMs(stage.avg_duration_ms)}
      </Text>
      {stage.std_dev_duration_ms !== null && (
        <Text font="secondary-mono" color="text-03">
          {`± ${formatDurationMs(stage.std_dev_duration_ms)}`}
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

interface StageRowProps {
  stage: IndexAttemptStageMetric;
  /** The longest max across the listed stages, which the bars scale to. */
  scale: number;
}
/** One stage: batch count, average, a min-to-max bar with the average marked, and max. */
function StageRow({ stage, scale }: StageRowProps) {
  const t = useTranslations("admin.connector");
  const format = useFormatter();
  const min = stage.min_duration_ms ?? 0;
  const max = stage.max_duration_ms ?? 0;
  // A std dev above the mean means batch times vary wildly, so flag the row.
  const uneven =
    stage.std_dev_duration_ms !== null &&
    stage.avg_duration_ms !== null &&
    stage.std_dev_duration_ms > stage.avg_duration_ms;

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
          {t(STAGE_LABEL_KEYS[stage.stage])}
        </Text>
      </Cell>
      <Cell width={BATCHES_WIDTH} align="end">
        <Text font="secondary-mono" color="text-03">
          {format.number(stage.event_count)}
        </Text>
      </Cell>
      <Cell width={AVERAGE_WIDTH}>
        <Average stage={stage} />
      </Cell>
      <Cell width={BAR_WIDTH}>
        <div className="relative my-1.5 h-1 w-full rounded-sm bg-background-tint-01">
          <div
            className="absolute top-0 h-1 rounded-sm bg-theme-blue-02"
            style={{
              insetInlineStart: percent(min, scale),
              width: percent(max - min, scale),
            }}
          />
          {stage.avg_duration_ms !== null && (
            <div
              className="absolute top-0 h-1 w-1 -ms-0.5 rounded-sm bg-theme-blue-05"
              style={{
                insetInlineStart: percent(stage.avg_duration_ms, scale),
              }}
            />
          )}
        </div>
      </Cell>
      <Cell width={MAX_WIDTH} align="end">
        <Text font="secondary-mono" color="text-03">
          {formatMs(stage.max_duration_ms)}
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
        {uneven && (
          <IconTooltip
            icon={SvgInfo}
            tooltip={t("stageDetails.uneven.tooltip")}
            aria-label={t("stageDetails.uneven.tooltip")}
          />
        )}
      </Section>
    </Section>
  );
}

interface StageRowsProps {
  rows: IndexAttemptStageMetric[];
  loaded: boolean;
  failed: boolean;
}
function StageRows({ rows, loaded, failed }: StageRowsProps) {
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
  if (rows.length === 0) {
    return (
      <Section padding={1} height="fit">
        <Text font="secondary-body" color="text-03">
          {t("stageMetrics.perBatch.empty")}
        </Text>
      </Section>
    );
  }
  const scale = Math.max(0, ...rows.map((row) => row.max_duration_ms ?? 0));
  return (
    <ShadowDiv>
      {rows.map((row) => (
        <StageRow key={row.stage} stage={row} scale={scale} />
      ))}
    </ShadowDiv>
  );
}

interface StageDetailsBodyProps {
  indexAttemptId: number;
}

/** How long each pipeline stage took per batch of one index attempt. The header carries the attempt's totals under each column title. */
function StageDetailsBody({ indexAttemptId }: StageDetailsBodyProps) {
  const t = useTranslations("admin.connector");
  const format = useFormatter();
  const { data, error } = useIndexAttemptStageMetrics(indexAttemptId);
  const stages = data?.stages ?? [];
  const total = stages.find((stage) => stage.stage === SUMMARY_STAGE);
  const rows = stages
    .filter(
      (stage) =>
        stage.scope === "BATCH_LEVEL" && !HIDDEN_STAGES.has(stage.stage)
    )
    .sort((a, b) => PIPELINE_ORDER[a.stage] - PIPELINE_ORDER[b.stage]);

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
          <Average stage={total} />
        </Cell>
        <Cell width={BAR_WIDTH + MAX_WIDTH} align="end">
          <ColumnTitle>{t("stageDetails.maxTime")}</ColumnTitle>
          <Text font="secondary-mono" color="text-03">
            {formatMs(total?.max_duration_ms)}
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
        rows={rows}
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
