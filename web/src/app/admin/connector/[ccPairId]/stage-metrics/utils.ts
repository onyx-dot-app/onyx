import { IndexAttemptStage, IndexAttemptStageMetric } from "@/lib/types";
import { PIPELINE_ORDER, STAGE_BAR_COLORS } from "./constants";
import { SortMode } from "./interfaces";
import { expectDefined } from "@/lib/utils";

// Sort per-batch stages according to the current sort mode. Pipeline order is
// the canonical enum declaration order; time-taken sorts descending by
// total duration so the long pole sits first.
export function sortPerBatchStages(
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

export function colorClassForStage(stage: IndexAttemptStage): string {
  const idx = PIPELINE_ORDER[stage] ?? 0;
  return expectDefined(
    STAGE_BAR_COLORS[idx % STAGE_BAR_COLORS.length],
    `No stage bar color for index ${idx}.`
  );
}
