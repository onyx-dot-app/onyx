"use client";

import { useTranslations } from "next-intl";
import { Text } from "@opal/components";
import { IndexAttemptStageMetric } from "@/lib/types";
import { formatDurationMs } from "@opal/time";

interface BatchTotalHeaderProps {
  batchTotal: IndexAttemptStageMetric | null;
}

export default function BatchTotalHeader({
  batchTotal,
}: BatchTotalHeaderProps) {
  const t = useTranslations("admin.connector");

  if (!batchTotal || batchTotal.event_count === 0) {
    return (
      <Text font="main-ui-action" color="text-04">
        {t("stageMetrics.batchTotal.empty")}
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
      {t("stageMetrics.batchTotal.summary", {
        avgLabel,
        count: batchTotal.event_count,
      })}
    </Text>
  );
}
