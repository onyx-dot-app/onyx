"use client";

import React from "react";
import { useTranslation } from "react-i18next";
import Text from "@/refresh-components/texts/Text";

export default function SignupText({ cloud }: { cloud?: boolean }) {
  const { t } = useTranslation();
  return (
    <div className="w-full">
      <Text as="p" headingH2 text05>
        {cloud ? t("auth.complete_signup") : t("auth.create_account")}
      </Text>
      <Text as="p" text03>
        {t("auth.get_started")}
      </Text>
    </div>
  );
}
