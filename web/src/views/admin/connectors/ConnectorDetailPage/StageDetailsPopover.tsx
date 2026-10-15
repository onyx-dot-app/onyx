"use client";

import { useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import {
  Button,
  Divider,
  Fold,
  IconTooltip,
  Popover,
  ShadowDiv,
  Spacer,
  Text,
} from "@opal/components";
import { Section } from "@opal/layouts";
import type { RichStr } from "@opal/types";
import { LineLoader } from "@opal/loaders";
import { useOpalStrings } from "@opal/strings";
import { formatDurationMs } from "@opal/time";
import {
  SvgAlertTriangle,
  SvgChevronDown,
  SvgChevronUp,
  SvgStackLine,
  SvgX,
} from "@opal/icons";
import useIndexAttemptStageMetrics from "@/hooks/useIndexAttemptStageMetrics";
import type { IndexAttemptStageMetric } from "@/lib/types";
import {
  PHASE_LABEL_KEYS,
  STAGE_LABEL_KEYS,
} from "@/lib/connectors/stageMetrics/constants";
import {
  isUneven,
  phaseScale,
  summarizePhases,
  type PhaseStage,
  type PhaseSummary,
} from "@/lib/connectors/stageMetrics/phases";

// BATCH_TOTAL feeds the header; the phase rows hold the other batch-level stages.
const SUMMARY_STAGE = "BATCH_TOTAL";

// Column widths from the mock, in rem: the stage name, the batch count, the
// average with its spread, the bar and the max. The actions take the rest.
const NAME_WIDTH = 9.25;
const BATCHES_WIDTH = 3.5;
const AVERAGE_WIDTH = 8.5;
const BAR_WIDTH = 5.75;
const MAX_WIDTH = 4;
// Stage rows sit under their phase row, indented by this much, in rem.
const STAGE_INDENT = 0.75;

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
        {formatDurationMs(avgMs)}
      </Text>
      {stdDevMs !== null && (
        <Text font="secondary-mono" color="text-03">
          {`± ${formatDurationMs(stdDevMs)}`}
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

interface TimingRowProps {
  label: string;
  /** Stage rows sit indented under their phase row. */
  indented?: boolean;
  /** `undefined` when the attempt never reached this stage or phase. */
  timing:
    | {
        batchCount: number;
        avgMs: number | null;
        stdDevMs: number | null;
        minMs: number | null;
        maxMs: number | null;
        uneven: boolean;
      }
    | undefined;
  /** The longest max across the listed rows, which the bars scale to. */
  scale: number;
  action?: React.ReactNode;
}
/** One row: batch count, average, a min-to-max bar with the average marked, and max. */
function TimingRow({
  label,
  indented = false,
  timing,
  scale,
  action,
}: TimingRowProps) {
  const t = useTranslations("admin.connector");
  const format = useFormatter();
  const min = timing?.minMs ?? 0;
  const max = timing?.maxMs ?? 0;

  return (
    <Section
      flexDirection="row"
      alignItems="center"
      justifyContent="start"
      gap={1}
      height="fit"
    >
      <Cell width={NAME_WIDTH}>
        <Section
          flexDirection="row"
          alignItems="center"
          justifyContent="start"
          gap={0}
          height="fit"
        >
          {indented && <Spacer orientation="horizontal" rem={STAGE_INDENT} />}
          <Text
            font="secondary-action"
            color={
              timing === undefined
                ? "text-02"
                : indented
                  ? "text-03"
                  : "text-04"
            }
          >
            {label}
          </Text>
        </Section>
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
          <Text font="secondary-body" color="text-02">
            {t("stageMetrics.notReached.label")}
          </Text>
        ) : (
          <div className="relative my-1.5 h-1 w-full rounded-sm bg-background-tint-01">
            <div
              className="absolute top-0 h-1 rounded-sm bg-theme-blue-02"
              style={{
                insetInlineStart: percent(min, scale),
                width: percent(max - min, scale),
              }}
            />
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
          {formatMs(timing?.maxMs)}
        </Text>
      </Cell>
      <Section
        flexDirection="row"
        alignItems="center"
        justifyContent="end"
        gap={0}
        width="auto"
        height="fit"
        className="min-w-0 flex-1"
      >
        {timing?.uneven && (
          <IconTooltip
            icon={SvgAlertTriangle}
            status="warning"
            tooltip={t("stageDetails.uneven.tooltip")}
            aria-label={t("stageDetails.uneven.tooltip")}
          />
        )}
        {action}
      </Section>
    </Section>
  );
}

interface StageRowProps {
  stage: PhaseStage;
  scale: number;
}
function StageRow({ stage: { stage, metric }, scale }: StageRowProps) {
  const t = useTranslations("admin.connector");
  return (
    <TimingRow
      label={t(STAGE_LABEL_KEYS[stage])}
      indented
      scale={scale}
      timing={
        metric && {
          batchCount: metric.event_count,
          avgMs: metric.avg_duration_ms,
          stdDevMs: metric.std_dev_duration_ms,
          minMs: metric.min_duration_ms,
          maxMs: metric.max_duration_ms,
          uneven: isUneven(metric),
        }
      }
    />
  );
}

interface PhaseRowsProps {
  phase: PhaseSummary;
  scale: number;
}
/** A phase's totals, folding open to every one of its stages. */
function PhaseRows({ phase, scale }: PhaseRowsProps) {
  const t = useTranslations("admin.connector");
  const strings = useOpalStrings();
  const [open, setOpen] = useState(false);
  const label = t(PHASE_LABEL_KEYS[phase.phase]);
  return (
    <Section alignItems="stretch" gap={0} height="fit">
      <TimingRow
        label={label}
        scale={scale}
        timing={
          phase.reached
            ? {
                batchCount: phase.batchCount,
                avgMs: phase.avgDurationMs,
                // Stage spreads do not add up to a phase spread.
                stdDevMs: null,
                minMs: phase.minDurationMs,
                maxMs: phase.maxDurationMs,
                uneven: phase.uneven,
              }
            : undefined
        }
        action={
          <Button
            icon={open ? SvgChevronUp : SvgChevronDown}
            prominence="tertiary"
            size="xs"
            aria-label={
              open
                ? strings.collapsibleFoldSection(label)
                : strings.collapsibleExpandSection(label)
            }
            aria-expanded={open}
            onClick={() => setOpen(!open)}
          />
        }
      />
      <Fold open={open}>
        <Section alignItems="stretch" gap={0} height="fit">
          {phase.stages.map((stage) => (
            <StageRow key={stage.stage} stage={stage} scale={scale} />
          ))}
        </Section>
      </Fold>
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
  const phases = summarizePhases(stages);
  const scale = phaseScale(phases);
  return (
    <ShadowDiv>
      {phases.map((phase) => (
        <PhaseRows key={phase.phase} phase={phase} scale={scale} />
      ))}
    </ShadowDiv>
  );
}

interface StageDetailsBodyProps {
  indexAttemptId: number;
}

/** How long each pipeline phase and its stages took per batch of one index attempt. The header carries the attempt's totals under each column title. */
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
