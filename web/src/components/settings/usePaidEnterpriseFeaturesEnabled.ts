"use client";

import { useContext } from "react";
import { SettingsContext } from "./SettingsProvider";

export function usePaidEnterpriseFeaturesEnabled() {
  const combinedSettings = useContext(SettingsContext);
  if (!combinedSettings) {
    return null;
  }
  return combinedSettings.enterpriseSettings !== null;
}
