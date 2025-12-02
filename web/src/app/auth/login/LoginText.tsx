"use client";

import React from "react";
import { useSettingsContext } from "@/components/settings/SettingsProvider";
import { useApplicationName } from "@/lib/hooks/useApplicationName";
import Text from "@/refresh-components/texts/Text";

const DEFAULT_APPLICATION_DESCRIPTION = "Your open source AI platform for work";

export default function LoginText() {
  const settings = useSettingsContext();
  const applicationName = useApplicationName();
  const applicationDescription =
    settings.enterpriseSettings?.application_description ||
    DEFAULT_APPLICATION_DESCRIPTION;

  return (
    <div className="w-full flex flex-col ">
      <Text headingH2 text05>
        Welcome to {applicationName}
      </Text>
      <Text text03 mainUiMuted>
        {applicationDescription}
      </Text>
    </div>
  );
}
