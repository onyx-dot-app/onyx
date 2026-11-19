"use client";

import { useTranslations } from "next-intl";
import { SettingsLayouts } from "@opal/layouts";

/** The plugins page while it loads. */
export default function PluginsLoading() {
  const t = useTranslations("actions.memberPlugins");
  return (
    <SettingsLayouts.Loading
      width="lg"
      title={t("title")}
      description={t("description")}
    />
  );
}
