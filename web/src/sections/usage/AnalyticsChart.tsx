import React from "react";
import { Card, EmptyMessageCard, MessageCard, Text } from "@opal/components";
import { SvgX } from "@opal/icons";
import { PageLoader, Section } from "@opal/layouts";
import type { RichStr } from "@opal/types";
import AreaChart from "@/refresh-components/AreaChart";
import { getDatesList } from "@/lib/usage/utils";
import { DateRange } from "@/refresh-components/DateRangePicker";
import { ChartSeries, ChartState } from "@/sections/usage/interfaces";

const CHART_BODY_HEIGHT = 20;

// "YYYY-MM-DD" parses as UTC midnight, which renders a day early west of UTC,
// so build the Date from the parts instead.
function formatDay(dateStr: string): string {
  const [year, month, day] = dateStr.split("-").map(Number);
  if (year === undefined || month === undefined || day === undefined) {
    return dateStr;
  }
  return new Date(year, month - 1, day).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

/** Keeps the underlying failure in the console when a chart shows its error card. */
export function useLoggedChartError(label: string, error: unknown): void {
  React.useEffect(() => {
    if (error) console.error(`${label} analytics request failed:`, error);
  }, [label, error]);
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
  timeRange: DateRange;
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
    timeRange?.from ?? new Date(earliest ?? Date.now()),
    timeRange?.to
  );

  return (
    <AreaChart
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
  timeRange: DateRange;
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
    <Card border="solid" rounding="lg" padding={6}>
      <Section
        flexDirection="column"
        justifyContent="start"
        alignItems="stretch"
        gap={0.5}
        width="full"
        height="fit"
      >
        {/* sm:flex-row / sm:items-center / sm:justify-between have no Section equivalent, kept as a raw div */}
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
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
        </div>
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
