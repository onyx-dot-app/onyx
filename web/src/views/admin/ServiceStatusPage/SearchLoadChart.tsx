"use client";

import {
  Area,
  AreaChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { cn } from "@opal/utils";
import type { SearchRatePoint } from "@/lib/service-status/types";
import {
  CHART_HEIGHT_CLASS,
  CHART_MARGIN,
  FAILED_COLOR,
  GRID_COLOR,
  SEARCH_COLOR,
  timeAxisProps,
} from "@/views/admin/ServiceStatusPage/chartFrame";

const MINUTE_MS = 60_000;

interface Point {
  at_ms: number;
  per_second: number;
  failed_per_second: number;
  failed: number;
}

interface SearchLoadChartProps {
  rate: SearchRatePoint[];
  startMs: number;
  endMs: number;
  formatTime: (ms: number) => string;
  renderTooltip: (
    atMs: number,
    perSecond: number,
    failed: number
  ) => React.ReactNode;
}

function isPoint(value: unknown): value is Point {
  return typeof value === "object" && value !== null && "per_second" in value;
}

/**
 * Searches per second, and the failed ones in red, one point per minute drawn
 * at the minute's middle. It has no y-axis or grid: the headline and the
 * tooltip give the rates.
 */
export default function SearchLoadChart({
  rate,
  startMs,
  endMs,
  formatTime,
  renderTooltip,
}: SearchLoadChartProps) {
  const points: Point[] = rate.map((point) => ({
    at_ms: point.minute_ms + MINUTE_MS / 2,
    per_second: point.count / point.seconds,
    failed_per_second: point.error_count / point.seconds,
    failed: point.error_count,
  }));
  const peak = Math.max(0, ...points.map((point) => point.per_second));

  return (
    // dir="ltr": time runs left to right in every locale.
    <div
      dir="ltr"
      className={cn(CHART_HEIGHT_CLASS, "w-full font-secondary-mono")}
    >
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={points} margin={CHART_MARGIN}>
          <XAxis {...timeAxisProps(startMs, endMs, formatTime)} />
          <YAxis hide type="number" domain={[0, peak > 0 ? "auto" : 1]} />
          <Tooltip
            cursor={{ stroke: GRID_COLOR }}
            content={({ active, payload }) => {
              const point: unknown = payload?.[0]?.payload;
              return active && isPoint(point)
                ? renderTooltip(point.at_ms, point.per_second, point.failed)
                : null;
            }}
          />
          <Area
            type="linear"
            dataKey="per_second"
            stroke={SEARCH_COLOR}
            strokeWidth={1.5}
            fill={SEARCH_COLOR}
            fillOpacity={0.12}
            isAnimationActive={false}
            dot={false}
            activeDot={{ r: 3 }}
          />
          {points.some((point) => point.failed > 0) && (
            <Area
              type="linear"
              dataKey="failed_per_second"
              stroke={FAILED_COLOR}
              strokeWidth={1.5}
              fill={FAILED_COLOR}
              fillOpacity={0.12}
              isAnimationActive={false}
              dot={false}
              activeDot={false}
            />
          )}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
