"use client";

import { useTranslations } from "next-intl";
import { SettingsLayouts } from "@opal/layouts";

/** The plugins page while it loads: its header over the page loader. */
export function PluginsPageLoader() {
  const t = useTranslations("actions.memberPlugins");
  return (
    <SettingsLayouts.Root width="lg" loading>
      <SettingsLayouts.Header
        title={t("title")}
        description={t("description")}
      />
      <SettingsLayouts.Body />
    </SettingsLayouts.Root>
  );
}
