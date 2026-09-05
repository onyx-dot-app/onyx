"use client";

import React from "react";
import { useTranslations } from "next-intl";
import { useSettings } from "@/lib/settings/hooks";
import Text from "@/refresh-components/texts/Text";

export default function LoginText() {
  const t = useTranslations("auth");
  const { appName, enterprise } = useSettings();
  const subtitle =
    enterprise?.custom_login_subtitle?.trim() ||
    t("login.welcomeSubtitle.text");
  return (
    <div className="w-full flex flex-col ">
      <Text as="p" headingH2 text05>
        {t("login.welcomeHeading.title", { appName })}
      </Text>
      <Text as="p" text03 mainUiMuted>
        {subtitle}
      </Text>
    </div>
  );
}
