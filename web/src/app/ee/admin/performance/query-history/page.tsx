import i18n from "@/i18n/init-server";
import k from "@/i18n/keys";

import { AdminPageTitle } from "@/components/admin/Title";
import { QueryHistoryTable } from "./QueryHistoryTable";
import { DatabaseIcon } from "@/components/icons/icons";

export default function QueryHistoryPage() {
  return (
    <main className="pt-4 mx-auto container">
      <AdminPageTitle
        title={i18n.t(k.QUERY_HISTORY_TITLE)}
        icon={<DatabaseIcon size={32} />}
      />

      <QueryHistoryTable />
    </main>
  );
}
