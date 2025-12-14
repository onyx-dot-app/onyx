"use client";

import { useContext } from "react";
import Logo from "@/refresh-components/Logo";
import { SettingsContext } from "./settings/SettingsProvider";

export function OnyxInitializingLoader() {
  const settings = useContext(SettingsContext);

  return (
    <div className="mx-auto my-auto animate-pulse">
      <Logo folded size={96} className="mx-auto mb-3" />
      <p className="text-lg text-text font-semibold">
        Initializing {settings?.enterpriseSettings?.application_name ?? "Onyx"}
      </p>
    </div>
  );
}
