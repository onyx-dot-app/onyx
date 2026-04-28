"use client";

import { useMemo, useState } from "react";
import { Button, Text } from "@opal/components";
import { Section } from "@/layouts/general-layouts";
import { IndexAttemptStageMetric } from "@/lib/types";
import { formatDurationMs } from "@/lib/time";
import { PIPELINE_ORDER, STAGE_LABELS } from "./constants";

interface AttemptOverheadProps {
  attemptStages: IndexAttemptStageMetric[];
}

// Per-attempt setup stages — one event each, no std dev, no chart. Rendered
// as a small disclosure beneath the main view to avoid overwhelming the
// admin while still surfacing one-off setup regressions.
export default function AttemptOverhead({
  attemptStages,
}: AttemptOverheadProps) {
  const [open, setOpen] = useState(false);
  const sorted = useMemo(() => {
    const copy = [...attemptStages];
    copy.sort(
      (a, b) => (PIPELINE_ORDER[a.stage] ?? 0) - (PIPELINE_ORDER[b.stage] ?? 0)
    );
    return copy;
  }, [attemptStages]);

  return (
    <Section alignItems="start" height="fit" width="full" gap={0.25}>
      <Button
        prominence="tertiary"
        size="sm"
        onClick={() => setOpen((o) => !o)}
      >
        {open ? "Hide attempt overhead" : "Show attempt overhead"}
      </Button>
      {open && <AttemptOverheadList stages={sorted} />}
    </Section>
  );
}

interface AttemptOverheadListProps {
  stages: IndexAttemptStageMetric[];
}

function AttemptOverheadList({ stages }: AttemptOverheadListProps) {
  return (
    <Section alignItems="stretch" height="fit" width="full" gap={0.125}>
      {stages.map((stage) => (
        <AttemptOverheadRow key={stage.stage} stage={stage} />
      ))}
    </Section>
  );
}

interface AttemptOverheadRowProps {
  stage: IndexAttemptStageMetric;
}

function AttemptOverheadRow({ stage }: AttemptOverheadRowProps) {
  return (
    <Section
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
    </Section>
  );
}
