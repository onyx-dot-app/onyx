import type { IndexAttemptStage, IndexAttemptStageMetric } from "@/lib/types";
import {
  PHASE_STAGES,
  STAGE_PHASES,
} from "@/lib/connectors/stageMetrics/constants";
import {
  phaseScale,
  summarizePhases,
} from "@/lib/connectors/stageMetrics/phases";

function metric(
  stage: IndexAttemptStage,
  overrides: Partial<IndexAttemptStageMetric> = {}
): IndexAttemptStageMetric {
  return {
    stage,
    scope: "BATCH_LEVEL",
    event_count: 2,
    total_duration_ms: 200,
    avg_duration_ms: 100,
    std_dev_duration_ms: 10,
    min_duration_ms: 90,
    max_duration_ms: 110,
    time_first_event: null,
    time_last_event: null,
    ...overrides,
  };
}

describe("summarizePhases", () => {
  it("lists every phase and stage even when nothing was recorded", () => {
    const phases = summarizePhases([]);
    expect(phases.map((phase) => phase.phase)).toEqual([...STAGE_PHASES]);
    for (const phase of phases) {
      expect(phase.reached).toBe(false);
      expect(phase.avgDurationMs).toBeNull();
      expect(phase.stages.map((stage) => stage.stage)).toEqual([
        ...PHASE_STAGES[phase.phase],
      ]);
      expect(phase.stages.every((stage) => stage.metric === undefined)).toBe(
        true
      );
    }
  });

  it("keeps the same stage rows for a run that skipped processing", () => {
    const fetchOnly = summarizePhases([metric("CONNECTOR_FETCH")]);
    const full = summarizePhases([
      metric("CONNECTOR_FETCH"),
      metric("CHUNKING"),
      metric("VECTOR_DB_WRITE"),
    ]);
    const shape = (phases: typeof full) =>
      phases.map((phase) => phase.stages.map((stage) => stage.stage));
    expect(shape(fetchOnly)).toEqual(shape(full));
    expect(fetchOnly.find((p) => p.phase === "process")?.reached).toBe(false);
    expect(full.find((p) => p.phase === "process")?.reached).toBe(true);
  });

  it("sums times, takes the largest batch count and skips nested waits", () => {
    const [, , process] = summarizePhases([
      metric("CHUNKING", { event_count: 3 }),
      metric("EMBEDDING", { event_count: 5, max_duration_ms: 400 }),
      metric("EMBEDDING_RATE_LIMIT_WAIT", { event_count: 7 }),
    ]);
    expect(process?.batchCount).toBe(7);
    expect(process?.avgDurationMs).toBe(200);
    expect(process?.minDurationMs).toBe(180);
    expect(process?.maxDurationMs).toBe(510);
  });

  it("ignores attempt-level and summary stages", () => {
    const phases = summarizePhases([
      metric("CONNECTOR_VALIDATION", { scope: "ATTEMPT_LEVEL" }),
      metric("BATCH_TOTAL"),
      metric("BATCH_UNACCOUNTED"),
    ]);
    expect(phases.some((phase) => phase.reached)).toBe(false);
  });

  it("flags a phase when one of its stages is uneven", () => {
    const [fetch] = summarizePhases([
      metric("HIERARCHY_UPSERT", { std_dev_duration_ms: 500 }),
    ]);
    expect(fetch?.uneven).toBe(true);
  });
});

describe("phaseScale", () => {
  it("covers a nested wait longer than its phase total", () => {
    const phases = summarizePhases([
      metric("EMBEDDING", { max_duration_ms: 100 }),
      metric("EMBEDDING_PROVIDER_THROTTLE_WAIT", { max_duration_ms: 900 }),
    ]);
    expect(phaseScale(phases)).toBe(900);
  });
});
