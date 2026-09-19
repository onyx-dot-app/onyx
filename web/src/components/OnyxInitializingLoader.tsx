"use client";

import { Logo } from "@/lib/app/components";
import { useSettings } from "@/lib/settings/hooks";
import { useTranslations } from "next-intl";

export default function OnyxInitializingLoader() {
  const t = useTranslations("common.initializingLoader");
  const { appName } = useSettings();

  return (
    <div className="mx-auto my-auto animate-pulse">
      <Logo folded size={96} className="mx-auto mb-3" />
      <p className="text-lg text-text font-semibold">
        {t("initializing.text", { appName })}
      </p>
    </div>
  );
}
