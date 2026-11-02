"use client";

import { useTranslations } from "next-intl";
import { SettingsLayouts } from "@opal/layouts";
import { SvgOnyxOctagon } from "@opal/icons";

/** The agents page while it loads: its header over the page loader. */
export function AgentsPageLoader() {
  const t = useTranslations("agents");
  return (
    <SettingsLayouts.Root loading>
      <SettingsLayouts.Header
        icon={SvgOnyxOctagon}
        title={t("navigation.header.title")}
        description={t("navigation.header.description")}
      />
      <SettingsLayouts.Body />
    </SettingsLayouts.Root>
  );
}
