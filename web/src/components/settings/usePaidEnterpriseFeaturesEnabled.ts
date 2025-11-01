"use client";

import { useSettingsContext } from "@/components/settings/SettingsProvider";

export function usePaidEnterpriseFeaturesEnabled() {
  const combinedSettings = useSettingsContext();
  return combinedSettings.enterpriseSettings !== null;
}
