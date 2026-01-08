"use client";

import React, { useContext } from "react";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import Text from "@/refresh-components/texts/Text";

export default function LoginText() {
  const settings = useContext(SettingsContext);
  return (
    <div className="w-full flex flex-col ">
      <Text as="p" headingH2 text05>
        Welcome to{" "}
        {(settings && settings?.enterpriseSettings?.application_name) || "Onyx"}
      </Text>
      <Text as="p" text03 mainUiMuted>
        Your open source AI platform for work
      </Text>
    </div>
  );
}
