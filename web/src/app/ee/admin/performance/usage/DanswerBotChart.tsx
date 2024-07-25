import { ThreeDotsLoader } from "@/components/Loading";
import { getDatesList, useDanswerBotAnalytics } from "../lib";
import {
  AreaChart,
  Card,
  Title,
  Text,
  DateRangePickerValue,
} from "@tremor/react";

export function DanswerBotChart({
  timeRange,
}: {
  timeRange: DateRangePickerValue;
}) {
  const {
    data: danswerBotAnalyticsData,
    isLoading: isDanswerBotAnalyticsLoading,
    error: danswerBotAnalyticsError,
  } = useDanswerBotAnalytics(timeRange);

  let chart;
  if (isDanswerBotAnalyticsLoading) {
    chart = (
      <div className="h-80 flex flex-col">
        <ThreeDotsLoader />
      </div>
    );
  } else if (!danswerBotAnalyticsData || danswerBotAnalyticsError) {
    chart = (
      <div className="h-80 text-red-600 text-bold flex flex-col">
        <p className="m-auto">Failed to fetch feedback data...</p>
      </div>
    );
  } else {
    const initialDate =
      timeRange.from || new Date(danswerBotAnalyticsData[0].date);
    const dateRange = getDatesList(initialDate);

    const dateToDanswerBotAnalytics = new Map(
      danswerBotAnalyticsData.map((danswerBotAnalyticsEntry) => [
        danswerBotAnalyticsEntry.date,
        danswerBotAnalyticsEntry,
      ])
    );

    chart = (
      <AreaChart
        className="mt-4 h-80"
        data={dateRange.map((dateStr) => {
          const danswerBotAnalyticsForDate =
            dateToDanswerBotAnalytics.get(dateStr);
          return {
            Day: dateStr,
            "Total Queries": danswerBotAnalyticsForDate?.total_queries || 0,
            "Automatically Resolved":
              danswerBotAnalyticsForDate?.auto_resolved || 0,
          };
        })}
        categories={["Total Queries", "Automatically Resolved"]}
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
      <Title>Slack Bot</Title>
      <Text>Total Queries vs Auto Resolved</Text>
      {chart}
    </Card>
  );
}
