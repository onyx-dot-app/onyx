import { ThreeDotsLoader } from "@/components/Loading";
import { getDatesList, useQueryAnalytics } from "../lib";
import Text from "@/components/ui/text";
import Title from "@/components/ui/title";

import { DateRangePickerValue } from "@/components/dateRangeSelectors/AdminDateRangeSelector";
import CardSection from "@/components/admin/CardSection";
import { AreaChartDisplay } from "@/components/ui/areaChart";

export function FeedbackChart({
  timeRange,
}: {
  timeRange: DateRangePickerValue;
}) {
  const {
    data: queryAnalyticsData,
    isLoading: isQueryAnalyticsLoading,
    error: queryAnalyticsError,
  } = useQueryAnalytics(timeRange);

  let chart;
  if (isQueryAnalyticsLoading) {
    chart = (
      <div className="h-80 flex flex-col">
        <ThreeDotsLoader />
      </div>
    );
  } else if (
    !queryAnalyticsData ||
    queryAnalyticsData[0] === undefined ||
    queryAnalyticsError
  ) {
    chart = (
      <div className="h-80 text-red-600 text-bold flex flex-col">
        <p className="m-auto">Failed to fetch feedback data...</p>
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
            "Positive Feedback": queryAnalyticsForDate?.total_likes || 0,
            "Negative Feedback": queryAnalyticsForDate?.total_dislikes || 0,
          };
        })}
        categories={["Positive Feedback", "Negative Feedback"]}
        index="Day"
        colors={["indigo", "fuchsia"]}
        yAxisWidth={60}
      />
    );
  }

  return (
    <CardSection className="mt-8">
      <Title>Feedback</Title>
      <Text>Thumbs Up / Thumbs Down over time</Text>
      {chart}
    </CardSection>
  );
}
