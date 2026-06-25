"use client";

import { SvgOnyxOctagon, SvgPlus } from "@opal/icons";
import { Button } from "@opal/components";
import { SettingsLayouts } from "@opal/layouts";
import { useTranslation } from "react-i18next";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { useAdminPageTitle } from "@/lib/admin-i18n";

import AgentsTable from "./AgentsPage/AgentsTable";

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function AgentsPage() {
  const { t } = useTranslation();
  const title = useAdminPageTitle(ADMIN_ROUTES.AGENTS);

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        title={title}
        description={t("admin.agents.description")}
        icon={SvgOnyxOctagon}
        rightChildren={
          <Button href="/app/agents/create?admin=true" icon={SvgPlus}>
            {t("admin.agents.new_agent")}
          </Button>
        }
      />
      <SettingsLayouts.Body>
        <AgentsTable />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
