"use client";

import { useAdminRouteTitle } from "@/lib/adminNavLabels";
import { useTranslations } from "next-intl";
import { DateRangePicker } from "@/refresh-components/DateRangePicker";
import { useTimeRange } from "@/lib/usage/hooks";
import {
  FeedbackChart,
  SlackChannelChart,
  UsageChart,
} from "@/views/admin/WorkspaceAnalyticsPage/AnalyticsCharts";
import { PersonaMessagesChart } from "@/views/admin/WorkspaceAnalyticsPage/PersonaMessagesChart";
import UsageReports from "@/views/admin/WorkspaceAnalyticsPage/UsageReports";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { Divider } from "@opal/components";
import { SettingsLayouts } from "@opal/layouts";

const route = ADMIN_ROUTES.WORKSPACE_ANALYTICS;

export default function WorkspaceAnalyticsPage() {
  const t = useTranslations("admin.analytics");
  const adminRouteTitle = useAdminRouteTitle();
  const [timeRange, setTimeRange] = useTimeRange();

  return (
    <SettingsLayouts.Root width="lg">
      <SettingsLayouts.Header
        icon={route.icon}
        title={adminRouteTitle(route)}
        description={t("page.description")}
        divider
        rightChildren={
          <DateRangePicker
            value={timeRange}
            onValueChange={(range) =>
              setTimeRange((previous) =>
                range
                  ? { ...range, selectValue: previous.selectValue }
                  : previous
              )
            }
          />
        }
      />
      <SettingsLayouts.Body>
        <UsageChart timeRange={timeRange} />
        <FeedbackChart timeRange={timeRange} />
        <SlackChannelChart timeRange={timeRange} />
        <PersonaMessagesChart timeRange={timeRange} />
        <Divider />
        <UsageReports />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
