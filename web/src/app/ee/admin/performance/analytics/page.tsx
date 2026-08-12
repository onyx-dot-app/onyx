"use client";

import { AdminDateRangeSelector } from "@/components/dateRangeSelectors/AdminDateRangeSelector";
import {
  FeedbackChart,
  SlackChannelChart,
  UsageChart,
} from "@/app/ee/admin/performance/usage/AnalyticsCharts";
import { PersonaMessagesChart } from "@/app/ee/admin/performance/usage/PersonaMessagesChart";
import { useTimeRange } from "@/app/ee/admin/performance/lib";
import UsageReports from "@/app/ee/admin/performance/usage/UsageReports";
import { useAdminAgents } from "@/lib/agents/hooks";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { Divider } from "@opal/components";
import { Section, SettingsLayouts } from "@opal/layouts";

const route = ADMIN_ROUTES.WORKSPACE_ANALYTICS;

export default function WorkspaceAnalyticsPage() {
  const [timeRange, setTimeRange] = useTimeRange();
  const {
    agents,
    error: agentsError,
    isLoading: agentsLoading,
  } = useAdminAgents();

  return (
    <SettingsLayouts.Root width="lg">
      <SettingsLayouts.Header
        icon={route.icon}
        title={route.title}
        description="Understand how your workspace uses Onyx across queries, feedback, and agents."
        divider
      />
      <SettingsLayouts.Body>
        <Section flexDirection="row" justifyContent="end" height="fit">
          <AdminDateRangeSelector
            value={timeRange}
            onValueChange={(value) => setTimeRange(value as any)}
          />
        </Section>
        <UsageChart timeRange={timeRange} />
        <FeedbackChart timeRange={timeRange} />
        <SlackChannelChart timeRange={timeRange} />
        <PersonaMessagesChart
          availablePersonas={agents}
          agentsError={agentsError}
          agentsLoading={agentsLoading}
          timeRange={timeRange}
        />
        <Divider />
        <UsageReports />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
