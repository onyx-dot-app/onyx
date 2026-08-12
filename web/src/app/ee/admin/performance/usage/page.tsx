"use client";

import { DateRangePicker } from "@/refresh-components/DateRangePicker";
import { useTimeRange } from "@/app/ee/admin/performance/lib";
import PerUserUsagePanel from "@/views/admin/PerUserUsagePanel";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { Divider } from "@opal/components";
import { SettingsLayouts } from "@opal/layouts";
import TokenRateLimitsPanel from "@/app/admin/token-rate-limits/TokenRateLimitsPanel";

const route = ADMIN_ROUTES.USAGE;

export default function UsagePage() {
  const [timeRange, setTimeRange] = useTimeRange();

  return (
    <SettingsLayouts.Root width="lg">
      <SettingsLayouts.Header
        icon={route.icon}
        title={route.title}
        description="Monitor workspace spend and review usage by user."
        divider
      />
      <SettingsLayouts.Body>
        <PerUserUsagePanel
          timeRange={timeRange}
          headerRight={
            <DateRangePicker
              value={timeRange}
              onValueChange={(value) => setTimeRange(value as any)}
            />
          }
        />
        <Divider />
        <TokenRateLimitsPanel embedded />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
