"use client";

import { AdminDateRangeSelector } from "@/components/dateRangeSelectors/AdminDateRangeSelector";
import { useTimeRange } from "@/app/ee/admin/performance/lib";
import PerUserUsagePanel from "@/views/admin/PerUserUsagePanel";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { SettingsLayouts } from "@opal/layouts";

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
            <AdminDateRangeSelector
              value={timeRange}
              onValueChange={(value) => setTimeRange(value as any)}
            />
          }
        />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
