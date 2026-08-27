"use client";

import MCPPageContent from "@/sections/actions/MCPPageContent";
import { useTranslations } from "next-intl";
import { SettingsLayouts } from "@opal/layouts";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

const route = ADMIN_ROUTES.MCP_ACTIONS;

export default function Main() {
  const t = useTranslations("admin.mcpActions");

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={route.icon}
        title={route.title}
        description={t("header.description")}
        divider
      />
      <SettingsLayouts.Body>
        <MCPPageContent />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
