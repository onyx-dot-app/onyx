"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Text } from "@opal/components";
import { Section } from "@/layouts/general-layouts";
import { IndexAttemptStageMetric } from "@/lib/types";
import { formatDurationMs } from "@opal/time";
import { PIPELINE_ORDER, STAGE_LABEL_KEYS } from "./constants";

interface AttemptOverheadProps {
  attemptStages: IndexAttemptStageMetric[];
}

// Per-attempt setup stages — one event each, no std dev, no chart. Rendered
// as a small disclosure beneath the main view to avoid overwhelming the
// admin while still surfacing one-off setup regressions.
export default function AttemptOverhead({
  attemptStages,
}: AttemptOverheadProps) {
  const t = useTranslations("admin.connector");
  const [open, setOpen] = useState(false);
  const sorted = useMemo(() => {
    const copy = [...attemptStages];
    copy.sort(
      (a, b) => (PIPELINE_ORDER[a.stage] ?? 0) - (PIPELINE_ORDER[b.stage] ?? 0)
    );
    return copy;
  }, [attemptStages]);

  return (
    <Section alignItems="start" height="fit" width="full" gap={1}>
      <Button
        prominence="tertiary"
        size="sm"
        onClick={() => setOpen((o) => !o)}
      >
        {open
          ? t("stageMetrics.attemptOverhead.hideButton.label")
          : t("stageMetrics.attemptOverhead.showButton.label")}
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
    <Section alignItems="stretch" height="fit" width="full" gap={0.5}>
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
  const t = useTranslations("admin.connector");

  return (
    <Section
      flexDirection="row"
      justifyContent="between"
      alignItems="center"
      width="full"
      height="fit"
      gap={4}
    >
      <Text font="secondary-body" color="text-04">
        {t(STAGE_LABEL_KEYS[stage.stage])}
      </Text>
      <Text font="secondary-body" color="text-03">
        {formatDurationMs(stage.total_duration_ms)}
      </Text>
    </Section>
  );
}
