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
const BARS_HEIGHT = 64;

// Labels sit on local hours divisible by this. At 24 they fall on midnight and show the date.
const TICK_HOURS: Record<CCPairThroughputWindow, number> = {
  "12h": 2,
  "24h": 4,
  "7d": 24,
};

const RUN_MARK_CLASS: Record<ValidStatuses, string> = {
  success: "bg-theme-blue-02",
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

/** Documents indexed in each slice of the window, with a mark per index run colored by its status. */
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

  return (
    // The SVG never flips for right-to-left text, so the marks must not either.
    <Section alignItems="stretch" gap={0.5} height="fit" dir="ltr">
      <div role="img" aria-label={t("ariaLabel")} className="w-full">
        <ResponsiveContainer width="100%" height={BARS_HEIGHT}>
          <BarChart
            data={slices}
            margin={{ top: 0, right: 0, bottom: 0, left: 0 }}
            barCategoryGap={1}
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
              tick={{ fontSize: 10, fill: "var(--text-03)" }}
              axisLine={false}
              tickLine={false}
              height={16}
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
      {/* One mark per run, placed where it started. */}
      <div className="relative h-2.5 w-full" aria-hidden>
        {data.runs.map((run, index) => (
          <div
            key={`${run.started}-${index}`}
            className={cn(
              "absolute top-0 h-full w-px",
              RUN_MARK_CLASS[run.status]
            )}
            style={{
              left: `${((Date.parse(run.started) - start) / (end - start)) * 100}%`,
            }}
          />
        ))}
      </div>
    </Section>
  );
}
