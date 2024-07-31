"use client";

import { HeaderTitle } from "@/components/header/Header";
import { Logo } from "@/components/EEA_Logo";
import { Logo_empty } from "@/components/EEA_Logo";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import { NEXT_PUBLIC_DO_NOT_USE_TOGGLE_OFF_DANSWER_POWERED } from "@/lib/constants";
import { useContext } from "react";

export default function FixedLogo() {
  const combinedSettings = useContext(SettingsContext);
  const settings = combinedSettings?.settings;
  const enterpriseSettings = combinedSettings?.enterpriseSettings;

  return (
    <div className="absolute flex z-40 left-2.5 top-2">
      <div className="max-w-[200px] flex gap-x-1 my-auto">
        <div className="flex-none invisible mb-auto">
          <Logo_empty width={30} />
        </div>
        <div className="">
          {enterpriseSettings && enterpriseSettings.application_name ? (
            <div>
              <HeaderTitle>{enterpriseSettings.application_name}</HeaderTitle>
              {!NEXT_PUBLIC_DO_NOT_USE_TOGGLE_OFF_DANSWER_POWERED && (
                <p className="text-xs text-subtle">Powered by Danswer</p>
              )}
            </div>
          ) : (
            <HeaderTitle>GPT Lab</HeaderTitle>
          )}
        </div>
      </div>
    </div>
  );
}
