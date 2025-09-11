"use client";
import i18n from "@/i18n/init";
import k from "./../../../../../i18n/keys";
import { ThreeDotsLoader } from "@/components/Loading";
import { getDatesList } from "@/app/ee/admin/performance/lib";
import { useEffect, useState, useMemo } from "react";
import {
  DateRangeSelector,
  DateRange,
} from "@/app/ee/admin/performance/DateRangeSelector";
import { useAssistants } from "@/components/context/AssistantsContext";
import { AssistantIcon } from "@/components/assistants/AssistantIcon";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { AreaChartDisplay } from "@/components/ui/areaChart";

type AssistantDailyUsageEntry = {
  date: string;
  total_messages: number;
  total_unique_users: number;
};

type AssistantStatsResponse = {
  daily_stats: AssistantDailyUsageEntry[];
  total_messages: number;
  total_unique_users: number;
};

export function AssistantStats({ assistantId }: { assistantId: number }) {
  const [assistantStats, setAssistantStats] =
    useState<AssistantStatsResponse | null>(null);
  const { assistants } = useAssistants();
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dateRange, setDateRange] = useState<DateRange>({
    from: new Date(new Date().setDate(new Date().getDate() - 30)),
    to: new Date(),
  });

  const assistant = useMemo(() => {
    return assistants.find((a) => a.id === assistantId);
  }, [assistants, assistantId]);

  useEffect(() => {
    async function fetchStats() {
      try {
        setIsLoading(true);
        setError(null);

        const res = await fetch(
          `/api/analytics/assistant/${assistantId}/stats?start=${
            dateRange?.from?.toISOString() || ""
          }&end=${dateRange?.to?.toISOString() || ""}`
        );

        if (!res.ok) {
          if (res.status === 403) {
            throw new Error(i18n.t(k.NO_PERMISSION_TO_VIEW_STATS));
          }
          throw new Error(i18n.t(k.FAILED_TO_GET_ASSISTANT_STATS));
        }

        const data = (await res.json()) as AssistantStatsResponse;
        setAssistantStats(data);
      } catch (err) {
        setError(
          err instanceof Error ? err.message : i18n.t(k.UNKNOWN_ERROR_OCCURRED)
        );
      } finally {
        setIsLoading(false);
      }
    }

    fetchStats();
  }, [assistantId, dateRange]);

  const chartData = useMemo(() => {
    if (!assistantStats?.daily_stats?.length || !dateRange) {
      return null;
    }

    const initialDate =
      dateRange.from ||
      new Date(
        Math.min(
          ...assistantStats.daily_stats.map((entry) =>
            new Date(entry.date).getTime()
          )
        )
      );
    const endDate = dateRange.to || new Date();

    const dateRangeList = getDatesList(initialDate);

    const statsMap = new Map(
      assistantStats.daily_stats.map((entry) => [entry.date, entry])
    );

    return dateRangeList
      .filter((date) => new Date(date) <= endDate)
      .map((dateStr) => {
        const dayData = statsMap.get(dateStr);
        return {
          Day: dateStr,
          Messages: dayData?.total_messages || 0,
          "Unique Users": dayData?.total_unique_users || 0,
        };
      });
  }, [assistantStats, dateRange]);

  const totalMessages = assistantStats?.total_messages ?? 0;
  const totalUniqueUsers = assistantStats?.total_unique_users ?? 0;

  let content;
  if (isLoading || !assistant) {
    content = (
      <div className="h-80 flex flex-col">
        <ThreeDotsLoader />
      </div>
    );
  } else if (error) {
    content = (
      <div className="h-80 text-red-600 font-bold flex flex-col">
        <p className="m-auto">{error}</p>
      </div>
    );
  } else if (!assistantStats?.daily_stats?.length) {
    content = (
      <div className="h-80 text-text-500 flex flex-col">
        <p className="m-auto">{i18n.t(k.NO_DATA_FOUND_FOR_THIS_ASSISTA)}</p>
      </div>
    );
  } else if (chartData) {
    content = (
      <AreaChartDisplay
        className="mt-4"
        data={chartData}
        categories={["Messages", "Unique Users"]}
        index="Day"
        colors={["#4A4A4A", "#A0A0A0"]}
        yAxisWidth={60}
      />
    );
  }

  return (
    <Card className="w-full">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <p className="text-base font-normal text-2xl">
          {i18n.t(k.ASSISTANT_ANALYTICS)}
        </p>
        <DateRangeSelector value={dateRange} onValueChange={setDateRange} />
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
          <Card>
            <CardContent className="pt-6">
              <div className="flex items-center space-x-4">
                {assistant && (
                  <AssistantIcon
                    disableToolip
                    size="large"
                    assistant={assistant}
                  />
                )}
                <div>
                  <h3 className="text-lg font-normal">{assistant?.name}</h3>
                  <p className="text-sm text-text-500">
                    {assistant?.description}
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-6">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-sm font-medium text-text-500">
                    {i18n.t(k.TOTAL_MESSAGES)}
                  </p>
                  <p className="text-2xl font-normal">{totalMessages}</p>
                </div>
                <div>
                  <p className="text-sm font-medium text-text-500">
                    {i18n.t(k.TOTAL_UNIQUE_USERS)}
                  </p>
                  <p className="text-2xl font-normal">{totalUniqueUsers}</p>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
        {content}
      </CardContent>
    </Card>
  );
}
