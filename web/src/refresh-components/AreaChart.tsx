"use client";

import React from "react";
import {
  Area,
  AreaChart as ReChartsAreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { cn } from "@opal/utils";

// Resolved through var() so series follow the active theme. Recharts writes
// these to SVG presentation attributes, where var() still resolves.
const DEFAULT_COLORS = [
  "var(--theme-purple-05)",
  "var(--theme-magenta-05)",
] as const;

export interface AreaChartProps {
  data?: Array<Record<string, string | number>>;
  categories?: string[];
  index?: string;
  colors?: readonly string[];
  showXAxis?: boolean;
  showYAxis?: boolean;
  yAxisWidth?: number;
  showAnimation?: boolean;
  showTooltip?: boolean;
  showGridLines?: boolean;
  connectNulls?: boolean;
  allowDecimals?: boolean;
  className?: string;
  xAxisFormatter?: (value: string) => string;
  yAxisFormatter?: (value: number) => string;
  stacked?: boolean;
}

/**
 * Area chart with no surrounding chrome, so callers own the card and heading.
 */
export default function AreaChart({
  data = [],
  categories = [],
  index,
  colors = DEFAULT_COLORS,
  showXAxis = true,
  showYAxis = true,
  yAxisWidth = 56,
  showAnimation = true,
  showTooltip = true,
  showGridLines = true,
  connectNulls = false,
  allowDecimals = true,
  className,
  xAxisFormatter = (dateStr: string) => dateStr,
  yAxisFormatter = (value: number) => value.toString(),
  stacked = false,
}: AreaChartProps) {
  return (
    <div className={cn("h-[350px] w-full", className)}>
      <ResponsiveContainer width="100%" height="100%">
        <ReChartsAreaChart
          data={data}
          margin={{ top: 10, right: 30, left: 0, bottom: 0 }}
        >
          {showGridLines && <CartesianGrid strokeDasharray="3 3" />}
          {showXAxis && (
            <XAxis
              dataKey={index}
              tickLine={false}
              axisLine={false}
              tickMargin={8}
              tickFormatter={(value) => xAxisFormatter(value)}
            />
          )}
          {showYAxis && (
            <YAxis
              width={yAxisWidth}
              tickLine={false}
              axisLine={false}
              tickFormatter={(value) => yAxisFormatter(value)}
              allowDecimals={allowDecimals}
            />
          )}
          {showTooltip && <Tooltip />}
          {categories.map((category, ind) => (
            <Area
              key={category}
              type="monotone"
              dataKey={category}
              stackId={stacked ? "1" : category}
              stroke={colors[ind % colors.length]}
              fill={colors[ind % colors.length]}
              fillOpacity={0.3}
              isAnimationActive={showAnimation}
              connectNulls={connectNulls}
            />
          ))}
        </ReChartsAreaChart>
      </ResponsiveContainer>
    </div>
  );
}
