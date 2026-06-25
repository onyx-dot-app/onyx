import SvgSimpleLoader from "@opal/icons/simple-loader";
import { getDatesList, useQueryAnalytics } from "../lib";
import { Text } from "@opal/components";
import Title from "@/components/ui/title";
import { useTranslation } from "react-i18next";

import { DateRangePickerValue } from "@/components/dateRangeSelectors/AdminDateRangeSelector";
import CardSection from "@/components/admin/CardSection";
import { AreaChartDisplay } from "@/components/ui/areaChart";

export function FeedbackChart({
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

  let chart;
  if (isQueryAnalyticsLoading) {
    chart = (
      <div className="h-80 flex flex-col items-center justify-center">
        <SvgSimpleLoader className="h-6 w-6" />
      </div>
    );
  } else if (
    !queryAnalyticsData ||
    queryAnalyticsData[0] === undefined ||
    queryAnalyticsError
  ) {
    chart = (
      <div className="h-80 text-red-600 text-bold flex flex-col">
        <p className="m-auto">{t("admin.usage.failed_to_fetch_feedback")}</p>
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

    chart = (
      <AreaChartDisplay
        className="mt-4"
        data={dateRange.map((dateStr) => {
          const queryAnalyticsForDate = dateToQueryAnalytics.get(dateStr);
          return {
            Day: dateStr,
            [t("admin.usage.positive_feedback")]: queryAnalyticsForDate?.total_likes || 0,
            [t("admin.usage.negative_feedback")]: queryAnalyticsForDate?.total_dislikes || 0,
          };
        })}
        categories={[t("admin.usage.positive_feedback"), t("admin.usage.negative_feedback")]}
        index="Day"
        colors={["indigo", "fuchsia"]}
        yAxisWidth={60}
      />
    );
  }

  return (
    <CardSection className="mt-8">
      <Title>{t("admin.usage.feedback_title")}</Title>
      <Text as="p">{t("admin.usage.feedback_over_time")}</Text>
      {chart}
    </CardSection>
  );
}
