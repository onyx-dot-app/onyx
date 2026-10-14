"use client";

import useSWR from "swr";
import { useFormatter, useTranslations } from "next-intl";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis } from "recharts";
import { Card, MessageCard, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { LineLoader } from "@opal/loaders";
import { cn } from "@opal/utils";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type {
  CCPairThroughputResponse,
  CCPairThroughputWindow,
} from "@/lib/connectors/types";
import type { ValidStatuses } from "@/lib/types";

const POLL_MS = 30_000;
const BARS_HEIGHT = 48;
const AXIS_HEIGHT = 16;

// Labels sit on local hours divisible by this. At 24 they fall on midnight and show the date.
const TICK_HOURS: Record<CCPairThroughputWindow, number> = {
  "12h": 2,
  "24h": 4,
  "7d": 24,
};

// The status strip's cell color for a slice a run of that status covered.
const RUN_CELL_CLASS: Record<ValidStatuses, string> = {
  success: "bg-action-selection-02",
  in_progress: "bg-theme-blue-05",
  not_started: "bg-theme-blue-05",
  completed_with_errors: "bg-status-warning-05",
  failed: "bg-status-error-05",
  invalid: "bg-status-error-05",
  canceled: "bg-background-neutral-03",
  interrupted: "bg-background-neutral-03",
};

interface Slice {
  /** The slice's middle, where its bar sits. */
  at: number;
  docs: number;
}

/** The local hours inside the window that are a multiple of `hours`. */
function axisTicks(start: number, end: number, hours: number): number[] {
  const tick = new Date(start);
  tick.setMinutes(0, 0, 0);
  const ticks: number[] = [];
  for (; tick.getTime() <= end; tick.setHours(tick.getHours() + 1)) {
    if (tick.getTime() >= start && tick.getHours() % hours === 0) {
      ticks.push(tick.getTime());
    }
  }
  return ticks;
}

interface Run {
  start: number;
  end: number;
  status: ValidStatuses;
}

// A slice several runs covered shows the one that needs attention most.
const STATUS_SEVERITY: Record<ValidStatuses, number> = {
  failed: 5,
  invalid: 5,
  completed_with_errors: 4,
  in_progress: 3,
  not_started: 3,
  success: 2,
  canceled: 1,
  interrupted: 1,
};

/** The status of the run that covered the slice, the most severe when several did. */
function sliceStatus(
  runs: Run[],
  sliceStart: number,
  sliceEnd: number
): ValidStatuses | null {
  let shown: Run | null = null;
  for (const run of runs) {
    // An instant run (one that failed at once) covers the slice it began in.
    if (
      run.start >= sliceEnd ||
      Math.max(run.end, run.start + 1) <= sliceStart
    ) {
      continue;
    }
    if (
      shown === null ||
      STATUS_SEVERITY[run.status] > STATUS_SEVERITY[shown.status]
    ) {
      shown = run;
    }
  }
  return shown?.status ?? null;
}

interface SliceTooltipProps {
  active?: boolean;
  payload?: { payload: Slice }[];
  sliceMs: number;
}
function SliceTooltip({ active, payload, sliceMs }: SliceTooltipProps) {
  const t = useTranslations("admin.connector.statusCard.throughput");
  const format = useFormatter();
  const slice = payload?.[0]?.payload;
  if (!active || slice === undefined) return null;
  const from = new Date(slice.at - sliceMs / 2);
  const to = new Date(slice.at + sliceMs / 2);
  return (
    <Card border="solid" rounding={2} padding={1}>
      <Text font="secondary-action" color="text-04">
        {t("tooltip", { count: slice.docs })}
      </Text>
      <Text font="secondary-body" color="text-03">
        {format.dateTimeRange(from, to, {
          month: "short",
          day: "numeric",
          hour: "2-digit",
          minute: "2-digit",
          hourCycle: "h23",
        })}
      </Text>
    </Card>
  );
}

export interface ThroughputChartProps {
  ccPairId: number;
  range: CCPairThroughputWindow;
}

/** Documents indexed in each slice of the window, over a strip that colors each slice by the run that covered it. */
export default function ThroughputChart({
  ccPairId,
  range,
}: ThroughputChartProps) {
  const t = useTranslations("admin.connector.statusCard.throughput");
  const format = useFormatter();
  const { data, error } = useSWR<CCPairThroughputResponse>(
    SWR_KEYS.ccPairThroughput(ccPairId, range),
    errorHandlingFetcher,
    { refreshInterval: POLL_MS, keepPreviousData: true }
  );
  if (error !== undefined) {
    return <MessageCard variant="error" title={t("loadError")} />;
  }
  if (data === undefined) return <LineLoader lines={3} />;

  const start = Date.parse(data.window_start);
  const end = Date.parse(data.window_end);
  const sliceMs = (end - start) / data.docs_indexed.length;
  const slices: Slice[] = data.docs_indexed.map((docs, index) => ({
    at: start + sliceMs * (index + 0.5),
    docs,
  }));
  const tickHours = TICK_HOURS[range];
  // A run still going covers up to the window's end.
  const runs: Run[] = data.runs.map((run) => ({
    start: Date.parse(run.started),
    end: run.ended === null ? end : Date.parse(run.ended),
    status: run.status,
  }));

  return (
    // The SVG never flips for right-to-left text, so the strip must not either.
    <Section alignItems="stretch" gap={0.5} height="fit" dir="ltr">
      {/* raw-ok: the chart is an SVG image, Section has no img role */}
      <div role="img" aria-label={t("ariaLabel")} className="w-full">
        <ResponsiveContainer width="100%" height={BARS_HEIGHT + AXIS_HEIGHT}>
          <BarChart
            data={slices}
            margin={{ top: 0, right: 0, bottom: 0, left: 0 }}
            barCategoryGap={1.5}
          >
            <XAxis
              dataKey="at"
              type="number"
              scale="time"
              domain={[start, end]}
              ticks={axisTicks(start, end, tickHours)}
              tickFormatter={(value: number) =>
                tickHours >= 24
                  ? format.dateTime(new Date(value), {
                      month: "short",
                      day: "numeric",
                    })
                  : format.dateTime(new Date(value), {
                      hour: "2-digit",
                      minute: "2-digit",
                      hourCycle: "h23",
                    })
              }
              tick={{
                fontSize: 10,
                fontFamily: "var(--font-dm-mono)",
                fill: "var(--text-03)",
              }}
              axisLine={{ stroke: "var(--border-01)" }}
              tickLine={{ stroke: "var(--border-01)" }}
              tickSize={2}
              height={AXIS_HEIGHT}
            />
            <Tooltip
              cursor={{ fill: "var(--background-tint-02)" }}
              content={<SliceTooltip sliceMs={sliceMs} />}
            />
            <Bar
              dataKey="docs"
              fill="var(--theme-blue-05)"
              radius={[1, 1, 0, 0]}
              isAnimationActive={false}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
      {/* raw-ok: the cells need a 1.5px gap, below Section's smallest spacing step */}
      <div className="flex h-2.5 w-full gap-[1.5px] px-[0.75px]" aria-hidden>
        {slices.map((slice) => {
          const status = sliceStatus(
            runs,
            slice.at - sliceMs / 2,
            slice.at + sliceMs / 2
          );
          return (
            <div
              key={slice.at}
              className={cn(
                "h-full min-w-px flex-1 rounded-[2px]",
                status === null ? undefined : RUN_CELL_CLASS[status]
              )}
            />
          );
        })}
      </div>
    </Section>
  );
}
