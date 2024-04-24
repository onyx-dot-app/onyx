import { EnterpriseSettings, Settings } from "@/app/admin/settings/interfaces";
import { CUSTOM_ANALYTICS_ENABLED, EE_ENABLED } from "@/lib/constants";
import { fetchSS } from "@/lib/utilsSS";

export async function fetchSettingsSS() {
  const tasks = [fetchSS("/settings")];
  if (EE_ENABLED) {
    tasks.push(fetchSS("/enterprise-settings"));
    if (CUSTOM_ANALYTICS_ENABLED) {
      tasks.push(fetchSS("/enterprise-settings/custom-analytics-script"));
    }
  }

  const results = await Promise.all(tasks);

  const settings = (await results[0].json()) as Settings;
  const enterpriseSettings =
    tasks.length > 1 ? ((await results[1].json()) as EnterpriseSettings) : null;
  const customAnalyticsScript = (
    tasks.length > 2 ? await results[2].json() : null
  ) as string | null;

  const combinedSettings = {
    settings,
    enterpriseSettings,
    customAnalyticsScript,
  };

  return combinedSettings;
}
