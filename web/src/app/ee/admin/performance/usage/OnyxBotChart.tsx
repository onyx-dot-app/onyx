import { ThreeDotsLoader } from "@/components/Loading";
import { getDatesList, useGlomiBotAnalytics } from "../lib";
import { DateRangePickerValue } from "@/components/dateRangeSelectors/AdminDateRangeSelector";
import { Text } from "@opal/components";
import Title from "@/components/ui/title";
import CardSection from "@/components/admin/CardSection";
import { AreaChartDisplay } from "@/components/ui/areaChart";

export function GlomiBotChart({
  timeRange,
}: {
  timeRange: DateRangePickerValue;
}) {
  const {
    data: onyxBotAnalyticsData,
    isLoading: isGlomiBotAnalyticsLoading,
    error: onyxBotAnalyticsError,
  } = useGlomiBotAnalytics(timeRange);

  let chart;
  if (isGlomiBotAnalyticsLoading) {
    chart = (
      <div className="h-80 flex flex-col">
        <ThreeDotsLoader />
      </div>
    );
  } else if (
    !onyxBotAnalyticsData ||
    onyxBotAnalyticsData[0] == undefined ||
    onyxBotAnalyticsError
  ) {
    chart = (
      <div className="h-80 text-red-600 text-bold flex flex-col">
        <p className="m-auto">Failed to fetch feedback data...</p>
      </div>
    );
  } else {
    const initialDate =
      timeRange.from || new Date(onyxBotAnalyticsData[0].date);
    const dateRange = getDatesList(initialDate);

    const dateToGlomiBotAnalytics = new Map(
      onyxBotAnalyticsData.map((onyxBotAnalyticsEntry) => [
        onyxBotAnalyticsEntry.date,
        onyxBotAnalyticsEntry,
      ])
    );

    chart = (
      <AreaChartDisplay
        className="mt-4"
        data={dateRange.map((dateStr) => {
          const onyxBotAnalyticsForDate = dateToGlomiBotAnalytics.get(dateStr);
          return {
            Day: dateStr,
            "Total Queries": onyxBotAnalyticsForDate?.total_queries || 0,
            "Automatically Resolved":
              onyxBotAnalyticsForDate?.auto_resolved || 0,
          };
        })}
        categories={["Total Queries", "Automatically Resolved"]}
        index="Day"
        colors={["indigo", "fuchsia"]}
        yAxisWidth={60}
      />
    );
  }

  return (
    <CardSection className="mt-8">
      <Title>Slack 频道</Title>
      <Text as="p">总查询数与自动解决数</Text>
      {chart}
    </CardSection>
  );
}
