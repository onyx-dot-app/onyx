"use client";

import { SettingsLayouts } from "@opal/layouts";
import OpenApiPageContent from "@/sections/actions/OpenApiPageContent";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { useAdminPageTitle } from "@/lib/admin-i18n";
import { useTranslation } from "react-i18next";

const route = ADMIN_ROUTES.OPENAPI_ACTIONS;

export default function Main() {
  const { t } = useTranslation();
  const title = useAdminPageTitle(route);

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={route.icon}
        title={title}
        description={t("admin.actions_open_api.desc")}
        divider
      />
      <SettingsLayouts.Body>
        <OpenApiPageContent />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
