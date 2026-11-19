"use client";

import { useTranslations } from "next-intl";
import { SettingsLayouts } from "@opal/layouts";
import { SvgSliders } from "@opal/icons";

/** The user settings while they load. */
export default function SettingsLoading() {
  const t = useTranslations("settings.layout");
  return (
    <SettingsLayouts.Loading
      width="lg"
      icon={SvgSliders}
      title={t("header.title")}
      divider
    />
  );
}
