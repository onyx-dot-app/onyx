import React from "react";
import { Card, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import SvgSimpleLoader from "@opal/icons/simple-loader";
import { AreaChartBody } from "@/components/ui/areaChart";
import { getDatesList } from "@/app/ee/admin/performance/lib";
import { DateRangePickerValue } from "@/components/dateRangeSelectors/AdminDateRangeSelector";

const SERIES_COLORS = ["indigo", "fuchsia"];

function formatDay(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

export interface ChartSeries {
  label: string;
  isEmpty: boolean;
  firstDate: string | undefined;
  valueForDate: (date: string) => number;
}

/**
 * Erases the entry type of one analytics endpoint so charts can combine series
 * that come from different endpoints.
 */
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

interface AnalyticsChartProps {
  title: string;
  description: string;
  timeRange: DateRangePickerValue;
  series: ChartSeries[];
  errorMessage: string;
  emptyMessage: string;
  isLoading?: boolean;
  error?: unknown;
  /** Shown instead of the chart when the caller needs a selection first. */
  prompt?: string;
  headerChildren?: React.ReactNode;
  stacked?: boolean;
  allowDecimals?: boolean;
  xAxisFormatter?: (value: string) => string;
  yAxisFormatter?: (value: number) => string;
}

function Placeholder({
  message,
  variant,
}: {
  message: string;
  variant: "error" | "neutral";
}) {
  return (
    <Section
      flexDirection="column"
      justifyContent="center"
      alignItems="center"
      height={20}
      width="full"
    >
      <Text
        font="main-ui-body"
        color={variant === "error" ? "status-error-05" : "text-03"}
      >
        {message}
      </Text>
    </Section>
  );
}

export function AnalyticsChart({
  title,
  description,
  timeRange,
  series,
  errorMessage,
  emptyMessage,
  isLoading,
  error,
  prompt,
  headerChildren,
  stacked = false,
  allowDecimals = true,
  xAxisFormatter = formatDay,
  yAxisFormatter,
}: AnalyticsChartProps) {
  let body;
  if (isLoading) {
    body = (
      <Section
        flexDirection="column"
        justifyContent="center"
        alignItems="center"
        height={20}
        width="full"
      >
        <SvgSimpleLoader className="h-6 w-6 animate-spin motion-reduce:animate-none" />
      </Section>
    );
  } else if (error) {
    body = <Placeholder message={errorMessage} variant="error" />;
  } else if (prompt !== undefined) {
    body = <Placeholder message={prompt} variant="neutral" />;
  } else if (series.every((entry) => entry.isEmpty)) {
    body = <Placeholder message={emptyMessage} variant="neutral" />;
  } else {
    const earliest = series
      .map((entry) => entry.firstDate)
      .filter((date): date is string => date !== undefined)
      .sort()[0];
    const dateRange = getDatesList(
      timeRange.from ?? new Date(earliest ?? Date.now()),
      timeRange.to
    );

    body = (
      <AreaChartBody
        data={dateRange.map((date) =>
          series.reduce<Record<string, string | number>>(
            (row, entry) => {
              row[entry.label] = entry.valueForDate(date);
              return row;
            },
            { Day: date }
          )
        )}
        categories={series.map((entry) => entry.label)}
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
        {body}
      </Section>
    </Card>
  );
}
