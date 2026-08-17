"use client";

import { useEffect, useState, useMemo } from "react";
import { Card, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import {
  DateRangePicker,
  DateRange,
} from "@/refresh-components/DateRangePicker";
import { useAgents } from "@/lib/agents/hooks";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import {
  AnalyticsChart,
  chartSeries,
  resolveChartState,
} from "@/sections/usage/AnalyticsChart";
import { ChartState } from "@/sections/usage/interfaces";

interface AgentDailyUsageEntry {
  date: string;
  total_messages: number;
  total_unique_users: number;
}

interface AgentStatsResponse {
  daily_stats: AgentDailyUsageEntry[];
  total_messages: number;
  total_unique_users: number;
}

interface SummaryMetricProps {
  label: string;
  value: number;
}

function SummaryMetric({ label, value }: SummaryMetricProps) {
  return (
    <Section
      flexDirection="column"
      justifyContent="start"
      alignItems="stretch"
      gap={0.125}
      width="full"
      height="fit"
    >
      <Text font="secondary-body" color="text-03">
        {label}
      </Text>
      <Text font="heading-h3">{value.toLocaleString()}</Text>
    </Section>
  );
}

interface AgentStatsProps {
  agentId: number;
}

export function AgentStats({ agentId }: AgentStatsProps) {
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

  const state: ChartState = error
    ? { status: "error", message: error }
    : resolveChartState({
        isLoading: isLoading || !agent,
        error: null,
        errorMessage: "Failed to fetch agent stats.",
        emptyMessage:
          "No data found for this agent in the selected date range.",
        series: [
          chartSeries(
            "Messages",
            agentStats?.daily_stats,
            (entry) => entry.total_messages
          ),
          chartSeries(
            "Unique Users",
            agentStats?.daily_stats,
            (entry) => entry.total_unique_users
          ),
        ],
      });

  return (
    <Section
      flexDirection="column"
      justifyContent="start"
      alignItems="stretch"
      gap={1}
      width="full"
      height="fit"
    >
      {/* sm:flex-row / sm:items-center / sm:justify-between have no Section equivalent, kept as a raw div */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <Text font="heading-h2">Agent Analytics</Text>
        <DateRangePicker value={dateRange} onValueChange={setDateRange} />
      </div>

      <Section
        flexDirection="row"
        justifyContent="start"
        alignItems="stretch"
        gap={0.5}
        wrap
        width="full"
        height="fit"
      >
        <div className="min-w-0 flex-1 basis-64">
          <Card border="solid" rounding="lg" padding={4}>
            <Section
              flexDirection="row"
              justifyContent="start"
              alignItems="center"
              gap={0.75}
              width="full"
              height="fit"
            >
              {agent && <AgentAvatar agent={agent} />}
              <Section
                flexDirection="column"
                justifyContent="start"
                alignItems="stretch"
                gap={0.125}
                width="full"
                height="fit"
              >
                <Text font="main-ui-action">{agent?.name ?? ""}</Text>
                <Text font="secondary-body" color="text-03">
                  {agent?.description ?? ""}
                </Text>
              </Section>
            </Section>
          </Card>
        </div>
        <div className="min-w-0 flex-1 basis-64">
          <Card border="solid" rounding="lg" padding={4}>
            <Section
              flexDirection="row"
              justifyContent="start"
              alignItems="stretch"
              gap={0.5}
              width="full"
              height="fit"
            >
              <SummaryMetric
                label="Total Messages"
                value={agentStats?.total_messages ?? 0}
              />
              <SummaryMetric
                label="Total Unique Users"
                value={agentStats?.total_unique_users ?? 0}
              />
            </Section>
          </Card>
        </div>
      </Section>

      <AnalyticsChart
        title="Messages and unique users"
        description="Per day for the selected range"
        timeRange={dateRange}
        state={state}
      />
    </Section>
  );
}
