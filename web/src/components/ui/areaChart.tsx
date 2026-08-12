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

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

interface AreaChartProps {
  data?: Array<Record<string, string | number>>;
  categories?: string[];
  index?: string;
  colors?: string[];
  showXAxis?: boolean;
  showYAxis?: boolean;
  yAxisWidth?: number;
  showAnimation?: boolean;
  showTooltip?: boolean;
  showGridLines?: boolean;
  connectNulls?: boolean;
  allowDecimals?: boolean;
  className?: string;
  title?: string;
  description?: string;
  xAxisFormatter?: (value: string) => string;
  yAxisFormatter?: (value: number) => string;
  stacked?: boolean;
}

// The chart itself, without any card chrome, so callers can place it inside
// their own container (e.g. an Opal Card).
export function AreaChartBody({
  data = [],
  categories = [],
  index,
  colors = ["indigo", "fuchsia"],
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
  yAxisFormatter = (number: number) => number.toString(),
  stacked = false,
}: Omit<AreaChartProps, "title" | "description">) {
  return (
    <div className={cn("h-[350px] w-full", className)}>
      <ResponsiveContainer width="100%" height="100%">
        <ReChartsAreaChart
          data={data}
          margin={{
            top: 10,
            right: 30,
            left: 0,
            bottom: 0,
          }}
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

export function AreaChartDisplay({
  className,
  title,
  description,
  ...bodyProps
}: AreaChartProps) {
  return (
    <Card className={className}>
      <CardHeader>
        {title && <CardTitle>{title}</CardTitle>}
        {description && <CardDescription>{description}</CardDescription>}
      </CardHeader>
      <CardContent>
        <AreaChartBody {...bodyProps} />
      </CardContent>
    </Card>
  );
}
