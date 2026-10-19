"use client";

import { Text } from "@opal/components";
import React from "react";
import { useTranslations } from "next-intl";
import { useSettings } from "@/lib/settings/hooks";

export default function LoginText() {
  const t = useTranslations("auth");
  const { appName, enterprise } = useSettings();
  const subtitle =
    enterprise?.custom_login_subtitle?.trim() ||
    t("login.welcomeSubtitle.text");
  return (
    <div className="w-full flex flex-col ">
      <Text font="heading-h2" color="text-05" as="p">
        {t("login.welcomeHeading.title", { appName })}
      </Text>
      <Text font="main-ui-muted" color="text-03" as="p">
        {subtitle}
      </Text>
    </div>
  );
}
