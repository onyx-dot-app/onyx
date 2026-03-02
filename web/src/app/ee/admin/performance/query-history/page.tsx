"use client";

import * as SettingsLayouts from "@/layouts/settings-layouts";
import { QueryHistoryTable } from "@/app/ee/admin/performance/query-history/QueryHistoryTable";
import { SvgServer } from "@opal/icons";
export default function QueryHistoryPage() {
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgServer}
        title="Query History"
        separator
      />

      <SettingsLayouts.Body>
        <QueryHistoryTable />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
