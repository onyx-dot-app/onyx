import {
  useOnyxBotAnalytics,
  useQueryAnalytics,
  useUserAnalytics,
} from "@/app/ee/admin/performance/lib";
import {
  AnalyticsChart,
  chartSeries,
} from "@/app/ee/admin/performance/usage/AnalyticsChart";
import { DateRangePickerValue } from "@/components/dateRangeSelectors/AdminDateRangeSelector";

interface AnalyticsChartProps {
  timeRange: DateRangePickerValue;
}

function formatCount(value: number): string {
  return new Intl.NumberFormat("en-US", {
    notation: "standard",
    maximumFractionDigits: 0,
  }).format(value);
}

export function UsageChart({ timeRange }: AnalyticsChartProps) {
  const queryAnalytics = useQueryAnalytics(timeRange);
  const userAnalytics = useUserAnalytics(timeRange);

  return (
    <AnalyticsChart
      title="Usage"
      description="Usage over time"
      timeRange={timeRange}
      isLoading={queryAnalytics.isLoading || userAnalytics.isLoading}
      error={queryAnalytics.error || userAnalytics.error}
      errorMessage="Failed to fetch query data..."
      emptyMessage="No queries in the selected time range"
      series={[
        chartSeries("Queries", queryAnalytics.data, (e) => e.total_queries),
        chartSeries(
          "Unique Users",
          userAnalytics.data,
          (e) => e.total_active_users
        ),
      ]}
      allowDecimals={false}
      yAxisFormatter={formatCount}
    />
  );
}

export function FeedbackChart({ timeRange }: AnalyticsChartProps) {
  const { data, isLoading, error } = useQueryAnalytics(timeRange);

  return (
    <AnalyticsChart
      title="Feedback"
      description="Thumbs Up / Thumbs Down over time"
      timeRange={timeRange}
      isLoading={isLoading}
      error={error}
      errorMessage="Failed to fetch feedback data..."
      emptyMessage="No feedback in the selected time range"
      series={[
        chartSeries("Positive Feedback", data, (e) => e.total_likes),
        chartSeries("Negative Feedback", data, (e) => e.total_dislikes),
      ]}
    />
  );
}

export function SlackChannelChart({ timeRange }: AnalyticsChartProps) {
  const { data, isLoading, error } = useOnyxBotAnalytics(timeRange);

  return (
    <AnalyticsChart
      title="Slack Channel"
      description="Total Queries vs Auto Resolved"
      timeRange={timeRange}
      isLoading={isLoading}
      error={error}
      errorMessage="Failed to fetch OnyxBot data..."
      emptyMessage="No OnyxBot activity in this workspace for the selected time range"
      series={[
        chartSeries("Total Queries", data, (e) => e.total_queries),
        chartSeries("Automatically Resolved", data, (e) => e.auto_resolved),
      ]}
    />
  );
}
