"use client";

import { AdminDateRangeSelector } from "@/components/dateRangeSelectors/AdminDateRangeSelector";
import { OnyxBotChart } from "@/app/ee/admin/performance/usage/OnyxBotChart";
import { FeedbackChart } from "@/app/ee/admin/performance/usage/FeedbackChart";
import { QueryPerformanceChart } from "@/app/ee/admin/performance/usage/QueryPerformanceChart";
import { PersonaMessagesChart } from "@/app/ee/admin/performance/usage/PersonaMessagesChart";
import { useTimeRange } from "@/app/ee/admin/performance/lib";
import UsageReports from "@/app/ee/admin/performance/usage/UsageReports";
import Separator from "@/refresh-components/Separator";
import { useAdminPersonas } from "@/hooks/useAdminPersonas";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import * as SettingsLayouts from "@/layouts/settings-layouts";

const route = ADMIN_ROUTES.USAGE;

export default function AnalyticsPage() {
  const [timeRange, setTimeRange] = useTimeRange();
  const { personas } = useAdminPersonas();

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header icon={route.icon} title={route.title} separator />
      <SettingsLayouts.Body>
        <AdminDateRangeSelector
          value={timeRange}
          onValueChange={(value) => setTimeRange(value as any)}
        />
        <QueryPerformanceChart timeRange={timeRange} />
        <FeedbackChart timeRange={timeRange} />
        <OnyxBotChart timeRange={timeRange} />
        <PersonaMessagesChart
          availablePersonas={personas}
          timeRange={timeRange}
        />
        <Separator />
        <UsageReports />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
