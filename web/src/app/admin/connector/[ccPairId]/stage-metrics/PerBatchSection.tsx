"use client";

import { Text } from "@opal/components";
import { Section } from "@/layouts/general-layouts";
import { IndexAttemptStageMetric } from "@/lib/types";
import { SortMode } from "./interfaces";
import SortToggle from "./SortToggle";
import PerBatchTable from "./PerBatchTable";

interface PerBatchSectionProps {
  perBatchStages: IndexAttemptStageMetric[];
  sortMode: SortMode;
  onSortModeChange: (mode: SortMode) => void;
}

export default function PerBatchSection({
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
    <Section alignItems="start" height="fit" width="full" gap={0.75}>
      <SortToggle sortMode={sortMode} onChange={onSortModeChange} />
      <PerBatchTable perBatchStages={perBatchStages} sortMode={sortMode} />
    </Section>
  );
}
