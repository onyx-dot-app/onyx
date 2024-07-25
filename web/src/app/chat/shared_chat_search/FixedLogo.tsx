"use client";

import { HeaderTitle } from "@/components/header/Header";
import { Logo } from "@/components/Logo";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import { useContext } from "react";

export default function FixedLogo() {
  const combinedSettings = useContext(SettingsContext);
  const settings = combinedSettings?.settings;
  const enterpriseSettings = combinedSettings?.enterpriseSettings;

  return (
    <div className="absolute flex z-40 left-4 top-2">
      {" "}
      <a href="/chat" className="ml-7 text-text-700 text-xl">
        <div>
          {enterpriseSettings && enterpriseSettings.application_name ? (
            <HeaderTitle>{enterpriseSettings.application_name}</HeaderTitle>
          ) : (
            <HeaderTitle>Danswer</HeaderTitle>
          )}
        </div>
      </a>
    </div>
  );
}
