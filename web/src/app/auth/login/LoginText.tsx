"use client";

import React, { useContext } from "react";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import Text from "@/refresh-components/texts/Text";

export default function LoginText() {
  const settings = useContext(SettingsContext);
  return (
    <div className="w-full flex flex-col ">
      <Text headingH2 text05>
        Bienvenue sur{" "}
        {(settings && settings?.enterpriseSettings?.application_name) || "Dom Engin."}
      </Text>
      <Text text03 mainUiMuted>
        Votre plateforme AI open source pour le travail
      </Text>
    </div>
  );
}
