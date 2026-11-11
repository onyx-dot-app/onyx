"use client";

import { useTranslations } from "next-intl";
import { SettingsLayouts } from "@opal/layouts";
import { SvgOnyxOctagon } from "@opal/icons";

/** The agents catalog while it loads. */
export default function AgentsCatalogLoading() {
  const t = useTranslations("agents");
  return (
    <SettingsLayouts.Loading
      icon={SvgOnyxOctagon}
      title={t("navigation.header.title")}
      description={t("navigation.header.description")}
    />
  );
}
