"use client";

import React from "react";
import { useSettings } from "@/lib/settings/hooks";
import Text from "@/refresh-components/texts/Text";
import { useTranslation } from "react-i18next";

export default function LoginText() {
  const { appName } = useSettings();
  const { t } = useTranslation();
  return (
    <div className="w-full flex flex-col ">
      <Text as="p" headingH2 text05>
        {t("auth.welcome_to")} {appName}
      </Text>
      <Text as="p" text03 mainUiMuted>
        {t("auth.tagline")}
      </Text>
    </div>
  );
}
