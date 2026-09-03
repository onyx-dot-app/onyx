"use client";

import { useAdminRouteTitle } from "@/lib/adminNavLabels";
import { useTranslations } from "next-intl";
import { DateRangePicker } from "@/refresh-components/DateRangePicker";
import { useTimeRange } from "@/lib/usage/hooks";
import PerUserUsagePanel from "@/views/admin/PerUserUsagePanel";
import SystemUsagePanel from "@/views/admin/SystemUsagePanel";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { Divider } from "@opal/components";
import { SettingsLayouts } from "@opal/layouts";
import TokenRateLimitsPanel from "@/app/admin/token-rate-limits/TokenRateLimitsPanel";

const route = ADMIN_ROUTES.USAGE;

export default function UsagePage() {
  const t = useTranslations("admin.usage");
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
            onValueChange={(value) => {
              if (!value) return;
              setTimeRange((previous) => ({
                ...value,
                selectValue: previous.selectValue,
              }));
            }}
            size="sm"
          />
        }
      />
      <SettingsLayouts.Body>
        <PerUserUsagePanel timeRange={timeRange} />
        <Divider />
        <SystemUsagePanel timeRange={timeRange} />
        <Divider />
        <TokenRateLimitsPanel embedded />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
