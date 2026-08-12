import React from "react";
import { Card, EmptyMessageCard, MessageCard, Text } from "@opal/components";
import { SvgX } from "@opal/icons";
import { PageLoader, Section } from "@opal/layouts";
import type { RichStr } from "@opal/types";
import { AreaChartBody } from "@/components/ui/areaChart";
import { getDatesList } from "@/app/ee/admin/performance/lib";
import { DateRangePickerValue } from "@/components/dateRangeSelectors/AdminDateRangeSelector";
import {
  ChartSeries,
  ChartState,
} from "@/views/admin/WorkspaceAnalyticsPage/interfaces";

// Resolved through var() so the series follow the active theme.
const SERIES_COLORS = ["var(--theme-purple-05)", "var(--theme-magenta-05)"];

const CHART_BODY_HEIGHT = 20;

function formatDay(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

export function chartSeries<T extends { date: string }>(
  label: string,
  data: T[] | undefined,
  value: (entry: T) => number
): ChartSeries {
  const entries = data ?? [];
  const byDate = new Map(entries.map((entry) => [entry.date, entry]));
  const dates = entries.map((entry) => entry.date).sort();

  return {
    label,
    isEmpty: entries.length === 0,
    firstDate: dates[0],
    valueForDate: (date) => {
      const entry = byDate.get(date);
      return entry === undefined ? 0 : value(entry);
    },
  };
}

interface ResolveChartStateArgs {
  isLoading: boolean;
  error: unknown;
  series: ChartSeries[];
  errorMessage: string;
  emptyMessage: string;
}

export function resolveChartState({
  isLoading,
  error,
  series,
  errorMessage,
  emptyMessage,
}: ResolveChartStateArgs): ChartState {
  if (error) return { status: "error", message: errorMessage };
  if (isLoading) return { status: "loading" };
  if (series.every((entry) => entry.isEmpty)) {
    return { status: "empty", message: emptyMessage };
  }
  return { status: "ready", series };
}

interface ChartBodyProps {
  state: ChartState;
  timeRange: DateRangePickerValue;
  stacked: boolean;
  allowDecimals: boolean;
  xAxisFormatter: (value: string) => string;
  yAxisFormatter?: (value: number) => string;
}

function ChartBody({
  state,
  timeRange,
  stacked,
  allowDecimals,
  xAxisFormatter,
  yAxisFormatter,
}: ChartBodyProps) {
  if (state.status === "error") {
    return <MessageCard variant="error" icon={SvgX} title={state.message} />;
  }

  if (state.status === "loading") {
    return (
      <Section
        flexDirection="column"
        justifyContent="center"
        alignItems="center"
        height={CHART_BODY_HEIGHT}
        width="full"
      >
        <PageLoader />
      </Section>
    );
  }

  if (state.status === "empty") {
    return <EmptyMessageCard sizePreset="main-ui" title={state.message} />;
  }

  const earliest = state.series
    .map((entry) => entry.firstDate)
    .filter((date): date is string => date !== undefined)
    .sort()[0];
  const dateRange = getDatesList(
    timeRange.from ?? new Date(earliest ?? Date.now()),
    timeRange.to
  );

  return (
    <AreaChartBody
      data={dateRange.map((date) =>
        state.series.reduce<Record<string, string | number>>(
          (row, entry) => {
            row[entry.label] = entry.valueForDate(date);
            return row;
          },
          { Day: date }
        )
      )}
      categories={state.series.map((entry) => entry.label)}
      index="Day"
      colors={SERIES_COLORS}
      yAxisWidth={60}
      stacked={stacked}
      allowDecimals={allowDecimals}
      xAxisFormatter={xAxisFormatter}
      {...(yAxisFormatter && { yAxisFormatter })}
    />
  );
}

interface AnalyticsChartProps {
  title: string | RichStr;
  description: string | RichStr;
  timeRange: DateRangePickerValue;
  state: ChartState;
  headerChildren?: React.ReactNode;
  stacked?: boolean;
  allowDecimals?: boolean;
  xAxisFormatter?: (value: string) => string;
  yAxisFormatter?: (value: number) => string;
}

export function AnalyticsChart({
  title,
  description,
  timeRange,
  state,
  headerChildren,
  stacked = false,
  allowDecimals = true,
  xAxisFormatter = formatDay,
  yAxisFormatter,
}: AnalyticsChartProps) {
  return (
    <Card border="solid" rounding="lg" padding="lg">
      <Section
        flexDirection="column"
        justifyContent="start"
        alignItems="stretch"
        gap={0.5}
        width="full"
        height="fit"
      >
        <Section
          flexDirection="column"
          justifyContent="start"
          alignItems="stretch"
          gap={0.125}
          width="full"
          height="fit"
        >
          <Text font="heading-h3">{title}</Text>
          <Text font="secondary-body" color="text-03">
            {description}
          </Text>
        </Section>
        {headerChildren}
        <ChartBody
          state={state}
          timeRange={timeRange}
          stacked={stacked}
          allowDecimals={allowDecimals}
          xAxisFormatter={xAxisFormatter}
          {...(yAxisFormatter && { yAxisFormatter })}
        />
      </Section>
    </Card>
  );
}
