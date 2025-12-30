"use client";

import { AdminPageTitle } from "@/components/admin/Title";
import { QueryHistoryTable } from "@/app/ee/admin/performance/query-history/QueryHistoryTable";
import { SvgServer } from "@opal/icons";
export default function QueryHistoryPage() {
  return (
    <div className="container">
      <AdminPageTitle title="Query History" icon={SvgServer} />

      <QueryHistoryTable />
    </div>
  );
}
