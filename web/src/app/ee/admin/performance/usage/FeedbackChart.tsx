import { ThreeDotsLoader } from "@/components/Loading";
import { getDatesList, useQueryAnalytics } from "../lib";
import {
  AreaChart,
  Card,
  Title,
  Text,
  DateRangePickerValue,
} from "@tremor/react";

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
  } else if (!queryAnalyticsData || queryAnalyticsError) {
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
      <AreaChart
        className="mt-4 h-80"
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
        valueFormatter={(number: number) =>
          `${Intl.NumberFormat("us").format(number).toString()}`
        }
        yAxisWidth={60}
      />
    );
  }

  return (
    <Card className="mt-8">
      <Title>Feedback</Title>
      <Text>Thumbs Up / Thumbs Down over time</Text>
      {chart}
    </Card>
  );
}
