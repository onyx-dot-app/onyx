import {
  useOnyxBotAnalytics,
  useQueryAnalytics,
  useUserAnalytics,
} from "@/lib/usage/hooks";
import {
  AnalyticsChart,
  chartSeries,
  resolveChartState,
  useLoggedChartError,
} from "@/sections/usage/AnalyticsChart";
import { DateRangePickerValue } from "@/refresh-components/DateRangePicker";

interface TimeRangeProps {
  timeRange: DateRangePickerValue;
}

function formatCount(value: number): string {
  return new Intl.NumberFormat("en-US", {
    notation: "standard",
    maximumFractionDigits: 0,
  }).format(value);
}

export function UsageChart({ timeRange }: TimeRangeProps) {
  const queryAnalytics = useQueryAnalytics(timeRange);
  const userAnalytics = useUserAnalytics(timeRange);

  useLoggedChartError("Query", queryAnalytics.error);
  useLoggedChartError("Active user", userAnalytics.error);

  return (
    <AnalyticsChart
      title="Usage"
      description="Usage over time"
      timeRange={timeRange}
      state={resolveChartState({
        isLoading: queryAnalytics.isLoading || userAnalytics.isLoading,
        error: queryAnalytics.error || userAnalytics.error,
        // Either endpoint can be the one that failed, so stay source-neutral.
        errorMessage: "Failed to fetch usage data.",
        emptyMessage: "No queries in the selected time range.",
        series: [
          chartSeries("Queries", queryAnalytics.data, (e) => e.total_queries),
          chartSeries(
            "Unique Users",
            userAnalytics.data,
            (e) => e.total_active_users
          ),
        ],
      })}
      allowDecimals={false}
      yAxisFormatter={formatCount}
    />
  );
}

export function FeedbackChart({ timeRange }: TimeRangeProps) {
  const { data, isLoading, error } = useQueryAnalytics(timeRange);

  useLoggedChartError("Feedback", error);

  return (
    <AnalyticsChart
      title="Feedback"
      description="Thumbs Up / Thumbs Down over time"
      timeRange={timeRange}
      state={resolveChartState({
        isLoading,
        error,
        errorMessage: "Failed to fetch feedback data.",
        emptyMessage: "No feedback in the selected time range.",
        series: [
          chartSeries("Positive Feedback", data, (e) => e.total_likes),
          chartSeries("Negative Feedback", data, (e) => e.total_dislikes),
        ],
      })}
    />
  );
}

export function SlackChannelChart({ timeRange }: TimeRangeProps) {
  const { data, isLoading, error } = useOnyxBotAnalytics(timeRange);

  useLoggedChartError("OnyxBot", error);

  return (
    <AnalyticsChart
      title="Slack Channel"
      description="Total Queries vs Auto Resolved"
      timeRange={timeRange}
      state={resolveChartState({
        isLoading,
        error,
        errorMessage: "Failed to fetch OnyxBot data.",
        emptyMessage:
          "No OnyxBot activity in this workspace for the selected time range.",
        series: [
          chartSeries("Total Queries", data, (e) => e.total_queries),
          chartSeries("Automatically Resolved", data, (e) => e.auto_resolved),
        ],
      })}
    />
  );
}
