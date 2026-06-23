"use client";

import { DateRangePickerValue } from "@/components/dateRangeSelectors/AdminDateRangeSelector";
import { getDatesList, useQueryAnalytics, useUserAnalytics } from "../lib";
import SvgSimpleLoader from "@opal/icons/simple-loader";
import { AreaChartDisplay } from "@/components/ui/areaChart";
import Title from "@/components/ui/title";
import { Text } from "@opal/components";
import CardSection from "@/components/admin/CardSection";

import { useTranslation } from "react-i18next";

export function QueryPerformanceChart({
  timeRange,
}: {
  timeRange: DateRangePickerValue;
}) {
  const { t } = useTranslation();
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
      <div className="h-80 flex flex-col items-center justify-center">
        <SvgSimpleLoader className="h-6 w-6" />
      </div>
    );
  } else if (
    !queryAnalyticsData ||
    queryAnalyticsData[0] === undefined ||
    !userAnalyticsData ||
    queryAnalyticsError ||
    userAnalyticsError
  ) {
    chart = (
      <div className="h-80 text-red-600 text-bold flex flex-col">
        <p className="m-auto">{t("admin.usage.failed_to_fetch")}</p>
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
      <AreaChartDisplay
        className="mt-4"
        stacked={false}
        data={dateRange.map((dateStr) => {
          const queryAnalyticsForDate = dateToQueryAnalytics.get(dateStr);
          const userAnalyticsForDate = dateToUserAnalytics.get(dateStr);
          return {
            Day: dateStr,
            [t("admin.usage.queries")]: queryAnalyticsForDate?.total_queries || 0,
            [t("admin.usage.unique_users")]: userAnalyticsForDate?.total_active_users || 0,
          };
        })}
        categories={[t("admin.usage.queries"), t("admin.usage.unique_users")]}
        index="Day"
        colors={["indigo", "fuchsia"]}
        yAxisFormatter={(number: number) =>
          new Intl.NumberFormat("en-US", {
            notation: "standard",
            maximumFractionDigits: 0,
          }).format(number)
        }
        xAxisFormatter={(dateStr: string) => {
          const date = new Date(dateStr);
          return date.toLocaleDateString("en-US", {
            month: "short",
            day: "numeric",
          });
        }}
        yAxisWidth={60}
        allowDecimals={false}
      />
    );
  }

  return (
    <CardSection className="mt-8">
      <Title>{t("admin.usage.usage_title")}</Title>
      <Text as="p">{t("admin.usage.usage_over_time")}</Text>
      {chart}
    </CardSection>
  );
}
