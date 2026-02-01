"use client";

import { useSettingsContext } from "@/providers/SettingsProvider";

export function usePaidEnterpriseFeaturesEnabled() {
  const combinedSettings = useSettingsContext();
  return combinedSettings.enterpriseSettings !== null;
}
