"use client";

import { useTranslations } from "next-intl";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import OpenApiPageContent from "@/sections/actions/OpenApiPageContent";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

const route = ADMIN_ROUTES.OPENAPI_ACTIONS;

export default function Main() {
  const t = useTranslations("admin.actions");
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={route.icon}
        title={route.title}
        description={t("openApiDescription")}
        separator
      />
      <SettingsLayouts.Body>
        <OpenApiPageContent />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
