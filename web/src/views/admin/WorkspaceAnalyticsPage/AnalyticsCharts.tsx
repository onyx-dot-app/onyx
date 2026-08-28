import { useLocale, useTranslations } from "next-intl";
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
import { formatTokenCount } from "@/lib/format";

interface TimeRangeProps {
  timeRange: DateRangePickerValue;
}

export function UsageChart({ timeRange }: TimeRangeProps) {
  const t = useTranslations("admin.analytics");
  const locale = useLocale();
  const queryAnalytics = useQueryAnalytics(timeRange);
  const userAnalytics = useUserAnalytics(timeRange);

  useLoggedChartError("Query", queryAnalytics.error);
  useLoggedChartError("Active user", userAnalytics.error);

  return (
    <AnalyticsChart
      title={t("usageChart.title")}
      description={t("usageChart.description")}
      timeRange={timeRange}
      state={resolveChartState({
        isLoading: queryAnalytics.isLoading || userAnalytics.isLoading,
        error: queryAnalytics.error || userAnalytics.error,
        // Either endpoint can be the one that failed, so stay source-neutral.
        errorMessage: t("usageChart.error"),
        emptyMessage: t("usageChart.empty"),
        series: [
          chartSeries(
            t("usageChart.series.queries.label"),
            queryAnalytics.data,
            (e) => e.total_queries
          ),
          chartSeries(
            t("usageChart.series.uniqueUsers.label"),
            userAnalytics.data,
            (e) => e.total_active_users
          ),
        ],
      })}
      allowDecimals={false}
      yAxisFormatter={(value) => formatTokenCount(value, locale)}
    />
  );
}

export function FeedbackChart({ timeRange }: TimeRangeProps) {
  const t = useTranslations("admin.analytics");
  const { data, isLoading, error } = useQueryAnalytics(timeRange);

  useLoggedChartError("Feedback", error);

  return (
    <AnalyticsChart
      title={t("feedbackChart.title")}
      description={t("feedbackChart.description")}
      timeRange={timeRange}
      state={resolveChartState({
        isLoading,
        error,
        errorMessage: t("feedbackChart.error"),
        emptyMessage: t("feedbackChart.empty"),
        series: [
          chartSeries(
            t("feedbackChart.series.positive.label"),
            data,
            (e) => e.total_likes
          ),
          chartSeries(
            t("feedbackChart.series.negative.label"),
            data,
            (e) => e.total_dislikes
          ),
        ],
      })}
    />
  );
}

export function SlackChannelChart({ timeRange }: TimeRangeProps) {
  const t = useTranslations("admin.analytics");
  const { data, isLoading, error } = useOnyxBotAnalytics(timeRange);

  useLoggedChartError("OnyxBot", error);

  return (
    <AnalyticsChart
      title={t("slackChannelChart.title")}
      description={t("slackChannelChart.description")}
      timeRange={timeRange}
      state={resolveChartState({
        isLoading,
        error,
        errorMessage: t("slackChannelChart.error"),
        emptyMessage: t("slackChannelChart.empty"),
        series: [
          chartSeries(
            t("slackChannelChart.series.totalQueries.label"),
            data,
            (e) => e.total_queries
          ),
          chartSeries(
            t("slackChannelChart.series.autoResolved.label"),
            data,
            (e) => e.auto_resolved
          ),
        ],
      })}
    />
  );
}
