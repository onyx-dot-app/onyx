"use client";

import { Text } from "@opal/components";
import { IndexAttemptStageMetric } from "@/lib/types";
import { formatDurationMs } from "@/lib/time";

interface BatchTotalHeaderProps {
  batchTotal: IndexAttemptStageMetric | null;
}

export default function BatchTotalHeader({
  batchTotal,
}: BatchTotalHeaderProps) {
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
