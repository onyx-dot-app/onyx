import { ThreeDotsLoader } from "@/components/Loading";
import { getDatesList } from "@/app/ee/admin/performance/lib";
import Text from "@/components/ui/text";
import Title from "@/components/ui/title";
import CardSection from "@/components/admin/CardSection";
import { AreaChartDisplay } from "@/components/ui/areaChart";
import { useEffect, useState, useMemo } from "react";
import {
  DateRangeSelector,
  DateRange,
} from "@/app/ee/admin/performance/DateRangeSelector";
import { useAssistants } from "@/components/context/AssistantsContext";
import { AssistantIcon } from "@/components/assistants/AssistantIcon";

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
            throw new Error("You don't have permission to view these stats.");
          }
          throw new Error("Failed to fetch assistant stats");
        }

        const data = (await res.json()) as AssistantStatsResponse;
        setAssistantStats(data);
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "An unknown error occurred"
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
      <div className="h-80 text-red-600 text-bold flex flex-col">
        <p className="m-auto">{error}</p>
      </div>
    );
  } else if (!assistantStats?.daily_stats?.length) {
    content = (
      <div className="h-80 text-gray-500 flex flex-col">
        <p className="m-auto">
          No data found for this assistant in the selected date range
        </p>
      </div>
    );
  } else if (chartData) {
    content = (
      <AreaChartDisplay
        className="mt-4"
        data={chartData}
        categories={["Messages", "Unique Users"]}
        index="Day"
        colors={["indigo", "fuchsia"]}
        yAxisWidth={60}
      />
    );
  }

  return (
    <CardSection className="mt-8">
      <div className="flex justify-between items-start mb-6">
        <div className="flex flex-col gap-2">
          <Title>Assistant Analytics</Title>
          <Text>
            Messages and unique users per day for the assistant{" "}
            <b>{assistant?.name}</b>
          </Text>
          <DateRangeSelector value={dateRange} onValueChange={setDateRange} />
        </div>
        {assistant && (
          <div className="bg-gray-100 p-4 rounded-lg shadow-sm">
            <div className="flex items-center mb-2">
              <AssistantIcon
                disableToolip
                size="medium"
                assistant={assistant}
              />
              <Title className="text-lg ml-3">{assistant?.name}</Title>
            </div>
            <Text className="text-gray-600 text-sm">
              {assistant?.description}
            </Text>
          </div>
        )}
      </div>
      <div className="flex flex-col gap-4">
        <div className="flex justify-between">
          <div>
            <Text className="font-semibold">Total Messages</Text>
            <Text>{totalMessages}</Text>
          </div>
          <div>
            <Text className="font-semibold">Total Unique Users</Text>
            <Text>{totalUniqueUsers}</Text>
          </div>
        </div>
      </div>
      {content}
    </CardSection>
  );
}
