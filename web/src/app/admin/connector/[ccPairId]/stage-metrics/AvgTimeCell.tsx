"use client";

import { Text } from "@opal/components";
import { Section } from "@/layouts/general-layouts";
import { IndexAttemptStageMetric } from "@/lib/types";
import { formatDurationMs } from "@/lib/time";
import { cn } from "@opal/utils";
import { colorClassForStage } from "./utils";

interface AvgTimeCellProps {
  stage: IndexAttemptStageMetric;
  maxAvgMs: number;
}

export default function AvgTimeCell({ stage, maxAvgMs }: AvgTimeCellProps) {
  const avg = stage.avg_duration_ms;
  const std = stage.std_dev_duration_ms;
  const avgLabel =
    avg !== null
      ? std !== null
        ? `${formatDurationMs(avg)} ± ${formatDurationMs(std)}`
        : formatDurationMs(avg)
      : "—";
  const avgPct = avg !== null && maxAvgMs > 0 ? (avg / maxAvgMs) * 100 : 0;

  return (
    <Section
      alignItems="start"
      justifyContent="center"
      width="full"
      height="fit"
      gap={0.25}
    >
      <Text font="secondary-body" color="text-05" nowrap>
        {avgLabel}
      </Text>
      {avgPct > 0 && (
        // Track + filled bar. Inline width is unavoidable since the bar
        // length is derived from a runtime ratio Tailwind can't express.
        <div
          aria-hidden="true"
          className="w-full h-1 rounded-full bg-background-tint-01 overflow-hidden"
        >
          <div
            className={cn(
              "h-full rounded-full",
              colorClassForStage(stage.stage)
            )}
            style={{ width: `${avgPct}%` }}
          />
        </div>
      )}
    </Section>
  );
}
