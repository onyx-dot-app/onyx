"use client";

import { AdminDateRangeSelector } from "@/components/dateRangeSelectors/AdminDateRangeSelector";
import { useTimeRange } from "@/app/ee/admin/performance/lib";
import PerUserUsagePanel from "@/views/admin/PerUserUsagePanel";
import TokenRateLimitsPanel from "@/app/admin/token-rate-limits/TokenRateLimitsPanel";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { Divider } from "@opal/components";
import { SettingsLayouts } from "@opal/layouts";
import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { Tier } from "@/lib/settings/types";

const route = ADMIN_ROUTES.USAGE;

export default function UsagePage() {
  const [timeRange, setTimeRange] = useTimeRange();
  const enterpriseTier = useTierAtLeast(Tier.ENTERPRISE);

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
        {enterpriseTier && (
          <>
            <Divider />
            <TokenRateLimitsPanel embedded />
          </>
        )}
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
