import type { IndexAttemptStage, IndexAttemptStageMetric } from "@/lib/types";
import {
  NESTED_STAGES,
  PHASE_STAGES,
  STAGE_PHASES,
  type StagePhase,
} from "@/lib/connectors/stageMetrics/constants";

export interface PhaseStage {
  stage: IndexAttemptStage;
  /** Absent when the attempt never reached the stage. */
  metric: IndexAttemptStageMetric | undefined;
}

export interface PhaseSummary {
  phase: StagePhase;
  stages: PhaseStage[];
  /** Whether the attempt reached any stage of the phase. */
  reached: boolean;
  /** The most batches any one stage of the phase saw. */
  batchCount: number;
  avgDurationMs: number | null;
  minDurationMs: number | null;
  maxDurationMs: number | null;
  /** Whether any stage of the phase has uneven batch times. */
  uneven: boolean;
}

/** A std dev above the mean means batch times vary wildly. */
export function isUneven(metric: IndexAttemptStageMetric): boolean {
  return (
    metric.std_dev_duration_ms !== null &&
    metric.avg_duration_ms !== null &&
    metric.std_dev_duration_ms > metric.avg_duration_ms
  );
}

function sumOrNull(values: (number | null)[]): number | null {
  const present = values.filter((value): value is number => value !== null);
  return present.length === 0
    ? null
    : present.reduce((total, value) => total + value, 0);
}

/** Every phase with every one of its stages, reached or not, so the shape is the same for every attempt. */
export function summarizePhases(
  metrics: IndexAttemptStageMetric[]
): PhaseSummary[] {
  const byStage = new Map(
    metrics
      .filter((metric) => metric.scope === "BATCH_LEVEL")
      .map((metric) => [metric.stage, metric])
  );
  return STAGE_PHASES.map((phase) => {
    const stages: PhaseStage[] = PHASE_STAGES[phase].map((stage) => ({
      stage,
      metric: byStage.get(stage),
    }));
    const reached = stages.flatMap(({ metric }) => (metric ? [metric] : []));
    const counted = reached.filter(
      (metric) => !NESTED_STAGES.has(metric.stage)
    );
    return {
      phase,
      stages,
      reached: reached.length > 0,
      batchCount: Math.max(0, ...reached.map((metric) => metric.event_count)),
      avgDurationMs: sumOrNull(counted.map((m) => m.avg_duration_ms)),
      minDurationMs: sumOrNull(counted.map((m) => m.min_duration_ms)),
      maxDurationMs: sumOrNull(counted.map((m) => m.max_duration_ms)),
      uneven: reached.some(isUneven),
    };
  });
}

/** The longest max across phases and stages, which every bar scales to. */
export function phaseScale(phases: PhaseSummary[]): number {
  return Math.max(
    0,
    ...phases.flatMap((phase) => [
      phase.maxDurationMs ?? 0,
      ...phase.stages.map(({ metric }) => metric?.max_duration_ms ?? 0),
    ])
  );
}
