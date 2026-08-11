import SvgSimpleLoader from "@opal/icons/simple-loader";
import { getDatesList, useOnyxBotAnalytics } from "../lib";
import { DateRangePickerValue } from "@/components/dateRangeSelectors/AdminDateRangeSelector";
import { Text } from "@opal/components";
import Title from "@/components/ui/title";
import CardSection from "@/components/admin/CardSection";
import { AreaChartDisplay } from "@/components/ui/areaChart";

export function OnyxBotChart({
  timeRange,
}: {
  timeRange: DateRangePickerValue;
}) {
  const {
    data: onyxBotAnalyticsData,
    isLoading: isOnyxBotAnalyticsLoading,
    error: onyxBotAnalyticsError,
  } = useOnyxBotAnalytics(timeRange);

  let chart;
  if (isOnyxBotAnalyticsLoading) {
    chart = (
      <div className="h-80 flex flex-col items-center justify-center">
        <SvgSimpleLoader className="h-6 w-6" />
      </div>
    );
  } else if (!onyxBotAnalyticsData || onyxBotAnalyticsError) {
    chart = (
      <div className="h-80 flex flex-col items-center justify-center">
        <Text font="main-ui-body" color="status-error-05">
          Failed to fetch OnyxBot data...
        </Text>
      </div>
    );
  } else if (onyxBotAnalyticsData[0] === undefined) {
    chart = (
      <div className="h-80 flex flex-col items-center justify-center">
        <Text font="main-ui-body" color="text-03">
          No OnyxBot activity in this workspace for the selected time range
        </Text>
      </div>
    );
  } else {
    const initialDate =
      timeRange.from || new Date(onyxBotAnalyticsData[0].date);
    const dateRange = getDatesList(initialDate, timeRange.to);

    const dateToOnyxBotAnalytics = new Map(
      onyxBotAnalyticsData.map((onyxBotAnalyticsEntry) => [
        onyxBotAnalyticsEntry.date,
        onyxBotAnalyticsEntry,
      ])
    );

    chart = (
      <AreaChartDisplay
        className="mt-4"
        data={dateRange.map((dateStr) => {
          const onyxBotAnalyticsForDate = dateToOnyxBotAnalytics.get(dateStr);
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
    <CardSection>
      <Title>Slack Channel</Title>
      <Text as="p">Total Queries vs Auto Resolved</Text>
      {chart}
    </CardSection>
  );
}
