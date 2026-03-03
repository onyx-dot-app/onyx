"use client";

import * as SettingsLayouts from "@/layouts/settings-layouts";
import { QueryHistoryTable } from "@/app/ee/admin/performance/query-history/QueryHistoryTable";
import { ADMIN_ROUTE_CONFIG, ADMIN_PATHS } from "@/lib/admin-routes";

const route = ADMIN_ROUTE_CONFIG[ADMIN_PATHS.QUERY_HISTORY]!;

export default function QueryHistoryPage() {
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header icon={route.icon} title={route.title} separator />

      <SettingsLayouts.Body>
        <QueryHistoryTable />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
