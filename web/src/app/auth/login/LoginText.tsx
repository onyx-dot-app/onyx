"use client";

import React, { useContext } from "react";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import Text from "@/refresh-components/texts/Text";

export default function LoginText() {
  const settings = useContext(SettingsContext);
  return (
    <div className="w-full flex flex-col items-center justify-center">
      <Text headingH3>
        Log In to{" "}
        {(settings && settings?.enterpriseSettings?.application_name) || "Onyx"}
      </Text>
    </div>
  );
}
