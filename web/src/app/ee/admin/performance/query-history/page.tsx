"use client";

import { AdminPageTitle } from "@/components/admin/Title";
import { QueryHistoryTable } from "./QueryHistoryTable";
import SvgServer from "@/icons/server";

export default function QueryHistoryPage() {
  return (
    <main className="pt-4 mx-auto container">
      <AdminPageTitle title="Query History" icon={SvgServer} />

      <QueryHistoryTable />
    </main>
  );
}
