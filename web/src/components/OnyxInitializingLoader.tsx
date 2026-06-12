"use client";

import { useContext } from "react";
import Logo from "@/refresh-components/Logo";
import { SettingsContext } from "@/providers/SettingsProvider";
import { APP_NAME } from "@/lib/brand";
import { useTranslations } from "next-intl";

export default function OnyxInitializingLoader() {
  const settings = useContext(SettingsContext);
  const t = useTranslations("brand");
  const appName = settings?.enterpriseSettings?.application_name ?? APP_NAME;

  return (
    <div className="mx-auto my-auto animate-pulse">
      <Logo folded size={96} className="mx-auto mb-3" />
      <p className="text-lg text-text font-semibold">
        {t("initializing", { appName })}
      </p>
    </div>
  );
}
