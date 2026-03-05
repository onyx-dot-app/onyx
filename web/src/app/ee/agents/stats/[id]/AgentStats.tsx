"use client";

import { ThreeDotsLoader } from "@/components/Loading";
import { getDatesList } from "@/app/ee/admin/performance/lib";
import { useEffect, useState, useMemo } from "react";
import {
  AdminDateRangeSelector,
  DateRange,
} from "@/components/dateRangeSelectors/AdminDateRangeSelector";
import { useAgents } from "@/hooks/useAgents";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { AreaChartDisplay } from "@/components/ui/areaChart";

type AgentDailyUsageEntry = {
  date: string;
  total_messages: number;
  total_unique_users: number;
};

type AgentStatsResponse = {
  daily_stats: AgentDailyUsageEntry[];
  total_messages: number;
  total_unique_users: number;
};

export function AgentStats({ agentId }: { agentId: number }) {
  const [agentStats, setAgentStats] = useState<AgentStatsResponse | null>(null);
  const { agents } = useAgents();
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dateRange, setDateRange] = useState<DateRange>({
    from: new Date(new Date().setDate(new Date().getDate() - 30)),
    to: new Date(),
  });

  const agent = useMemo(() => {
    return agents.find((a) => a.id === agentId);
  }, [agents, agentId]);

  useEffect(() => {
    async function fetchStats() {
      try {
        setIsLoading(true);
        setError(null);

        const res = await fetch(
          `/api/analytics/assistant/${agentId}/stats?start=${
            dateRange?.from?.toISOString() || ""
          }&end=${dateRange?.to?.toISOString() || ""}`
        );

        if (!res.ok) {
          if (res.status === 403) {
            throw new Error("You don't have permission to view these stats.");
          }
          throw new Error("Failed to fetch agent stats");
        }

        const data = (await res.json()) as AgentStatsResponse;
        setAgentStats(data);
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "An unknown error occurred"
        );
      } finally {
        setIsLoading(false);
      }
    }

    fetchStats();
  }, [agentId, dateRange]);

  const chartData = useMemo(() => {
    if (!agentStats?.daily_stats?.length || !dateRange) {
      return null;
    }

    const initialDate =
      dateRange.from ||
      new Date(
        Math.min(
          ...agentStats.daily_stats.map((entry) =>
            new Date(entry.date).getTime()
          )
        )
      );
    const endDate = dateRange.to || new Date();

    const dateRangeList = getDatesList(initialDate);

    const statsMap = new Map(
      agentStats.daily_stats.map((entry) => [entry.date, entry])
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
  }, [agentStats, dateRange]);

  const totalMessages = agentStats?.total_messages ?? 0;
  const totalUniqueUsers = agentStats?.total_unique_users ?? 0;

  let content;
  if (isLoading || !agent) {
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
  } else if (!agentStats?.daily_stats?.length) {
    content = (
      <div className="h-80 text-text-500 flex flex-col">
        <p className="m-auto">
          No data found for this agent in the selected date range
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
        colors={["#4A4A4A", "#A0A0A0"]}
        yAxisWidth={60}
      />
    );
  }

  return (
    <Card className="w-full">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <p className="text-base font-normal text-2xl">Agent Analytics</p>
        <AdminDateRangeSelector
          value={dateRange}
          onValueChange={setDateRange}
        />
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
          <Card>
            <CardContent className="pt-6">
              <div className="flex items-center space-x-4">
                {agent && <AgentAvatar agent={agent} />}
                <div>
                  <h3 className="text-lg font-normal">{agent?.name}</h3>
                  <p className="text-sm text-text-500">{agent?.description}</p>
                </div>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-6">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-sm font-medium text-text-500">
                    Total Messages
                  </p>
                  <p className="text-2xl font-normal">{totalMessages}</p>
                </div>
                <div>
                  <p className="text-sm font-medium text-text-500">
                    Total Unique Users
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
