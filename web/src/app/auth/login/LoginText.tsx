"use client";

import React from "react";
import { useTranslations } from "next-intl";
import { useSettings } from "@/lib/settings/hooks";
import { Text } from "@opal/components";

export default function LoginText() {
  const t = useTranslations("auth");
  const { appName, enterprise } = useSettings();
  const subtitle =
    enterprise?.custom_login_subtitle?.trim() ||
    t("login.welcomeSubtitle.text");
  return (
    <div className="w-full flex flex-col ">
      <Text as="p" font="heading-h2" color="text-05">
        {t("login.welcomeHeading.title", { appName })}
      </Text>
      <Text as="p" font="main-ui-muted" color="text-03">
        {subtitle}
      </Text>
    </div>
  );
}
