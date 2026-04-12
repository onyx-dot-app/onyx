"use client";

import { useTranslations } from "next-intl";
import MCPPageContent from "@/sections/actions/MCPPageContent";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

const route = ADMIN_ROUTES.MCP_ACTIONS;

export default function Main() {
  const t = useTranslations("admin.actions");
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={route.icon}
        title={route.title}
        description={t("mcpDescription")}
        separator
      />
      <SettingsLayouts.Body>
        <MCPPageContent />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
