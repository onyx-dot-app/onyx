"use client";

import {
  Card,
  AreaChart,
  Title,
  Text,
  DateRangePickerValue,
} from "@tremor/react";
import { getDatesList, useQueryAnalytics, useUserAnalytics } from "../lib";
import { ThreeDotsLoader } from "@/components/Loading";

export function QueryPerformanceChart({
  timeRange,
}: {
  timeRange: DateRangePickerValue;
}) {
  const {
    data: queryAnalyticsData,
    isLoading: isQueryAnalyticsLoading,
    error: queryAnalyticsError,
  } = useQueryAnalytics(timeRange);
  const {
    data: userAnalyticsData,
    isLoading: isUserAnalyticsLoading,
    error: userAnalyticsError,
  } = useUserAnalytics(timeRange);

  let chart;
  if (isQueryAnalyticsLoading || isUserAnalyticsLoading) {
    chart = (
      <div className="h-80 flex flex-col">
        <ThreeDotsLoader />
      </div>
    );
  } else if (
    !queryAnalyticsData ||
    !userAnalyticsData ||
    queryAnalyticsError ||
    userAnalyticsError
  ) {
    chart = (
      <div className="h-80 text-red-600 text-bold flex flex-col">
        <p className="m-auto">Failed to fetch query data...</p>
      </div>
    );
  } else {
    const initialDate = timeRange.from || new Date(queryAnalyticsData[0].date);
    const dateRange = getDatesList(initialDate);

    const dateToQueryAnalytics = new Map(
      queryAnalyticsData.map((queryAnalyticsEntry) => [
        queryAnalyticsEntry.date,
        queryAnalyticsEntry,
      ])
    );
    const dateToUserAnalytics = new Map(
      userAnalyticsData.map((userAnalyticsEntry) => [
        userAnalyticsEntry.date,
        userAnalyticsEntry,
      ])
    );

    chart = (
      <AreaChart
        className="h-80"
        data={dateRange.map((dateStr) => {
          const queryAnalyticsForDate = dateToQueryAnalytics.get(dateStr);
          const userAnalyticsForDate = dateToUserAnalytics.get(dateStr);
          return {
            Day: dateStr,
            Queries: queryAnalyticsForDate?.total_queries || 0,
            "Unique Users": userAnalyticsForDate?.total_active_users || 0,
          };
        })}
        categories={["Queries", "Unique Users"]}
        index="Day"
        colors={["indigo", "fuchsia"]}
        valueFormatter={(number: number) =>
          `${Intl.NumberFormat("us").format(number).toString()}`
        }
        yAxisWidth={60}
      />
    );
  }

  return (
    <Card className="mt-8">
      <Title>Usage</Title>
      <Text>Usage over time</Text>
      {chart}
    </Card>
  );
}
