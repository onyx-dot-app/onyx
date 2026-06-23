"use client";

import MCPPageContent from "@/sections/actions/MCPPageContent";
import { SettingsLayouts } from "@opal/layouts";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { useAdminPageTitle } from "@/lib/admin-i18n";
import { useTranslation } from "react-i18next";

const route = ADMIN_ROUTES.MCP_ACTIONS;

export default function Main() {
  const { t } = useTranslation();
  const title = useAdminPageTitle(route);

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={route.icon}
        title={title}
        description={t("admin.actions_mcp.desc")}
        divider
      />
      <SettingsLayouts.Body>
        <MCPPageContent />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
