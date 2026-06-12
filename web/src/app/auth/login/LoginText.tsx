"use client";

import React from "react";
import { useTranslations } from "next-intl";
import Text from "@/refresh-components/texts/Text";

export default function LoginText() {
  const t = useTranslations("auth");
  return (
    <div className="w-full flex flex-col ">
      <Text as="p" headingH2 text05>
        {t("title")}
      </Text>
      <Text as="p" text03 mainUiMuted>
        {t("subtitle")}
      </Text>
    </div>
  );
}
