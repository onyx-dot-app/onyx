import {
  CombinedSettings,
  EnterpriseSettings,
  ApplicationStatus,
  Settings,
  QueryHistoryType,
} from "@/lib/settings/types";
import {
  CUSTOM_ANALYTICS_ENABLED,
  HOST_URL,
  SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED,
} from "@/lib/constants";
import { fetchSS } from "@/lib/utilsSS";
import { getWebVersion } from "@/lib/version";

export async function fetchStandardSettingsSS(): Promise<Settings | null> {
  try {
    const response = await fetchSS("/settings");
    if (!response?.ok) return null;
    return response.json();
  } catch {
    return null;
  }
}

export async function fetchEnterpriseSettingsSS(): Promise<EnterpriseSettings | null> {
  try {
    const response = await fetchSS("/enterprise-settings");
    if (!response?.ok) return null;
    return response.json();
  } catch {
    return null;
  }
}

async function fetchCustomAnalyticsScriptSS(): Promise<string | null> {
  try {
    const response = await fetchSS(
      "/enterprise-settings/custom-analytics-script"
    );
    if (!response?.ok) return null;
    return response.json();
  } catch {
    return null;
  }
}

export async function fetchSettingsSS(): Promise<CombinedSettings | null> {
  const settingsTask = fetchSS("/settings");
  const enterpriseTask = SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED
    ? fetchSS("/enterprise-settings")
    : Promise.resolve(null);
  const analyticsTask =
    SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED &&
    CUSTOM_ANALYTICS_ENABLED
      ? fetchSS("/enterprise-settings/custom-analytics-script")
      : Promise.resolve(null);

  try {
    const [settingsResponse, enterpriseResponse, analyticsResponse] =
      await Promise.all([settingsTask, enterpriseTask, analyticsTask]);

    let settings: Settings;
    if (!settingsResponse) {
      throw new Error("Standard settings fetch failed.");
    }
    if (!settingsResponse.ok) {
      if (settingsResponse.status === 403 || settingsResponse.status === 401) {
        settings = {
          auto_scroll: true,
          application_status: ApplicationStatus.ACTIVE,
          gpu_enabled: false,
          maximum_chat_retention_days: null,
          notifications: [],
          needs_reindexing: false,
          anonymous_user_enabled: false,
          invite_only_enabled: false,
          deep_research_enabled: true,
          temperature_override_enabled: true,
          query_history_type: QueryHistoryType.NORMAL,
        };
      } else {
        throw new Error(
          `fetchSettingsSS: settings failed status=${
            settingsResponse.status
          } body=${await settingsResponse.text()}`
        );
      }
    } else {
      settings = await settingsResponse.json();
    }

    let enterpriseSettings: EnterpriseSettings | null = null;
    if (enterpriseResponse) {
      if (enterpriseResponse.ok) {
        enterpriseSettings = await enterpriseResponse.json();
      } else if (
        enterpriseResponse.status !== 403 &&
        enterpriseResponse.status !== 401
      ) {
        throw new Error(
          `fetchSettingsSS: enterprise failed status=${
            enterpriseResponse.status
          } body=${await enterpriseResponse.text()}`
        );
      }
    }

    let customAnalyticsScript: string | null = null;
    if (analyticsResponse) {
      if (analyticsResponse.ok) {
        customAnalyticsScript = await analyticsResponse.json();
      } else if (analyticsResponse.status !== 403) {
        throw new Error(
          `fetchSettingsSS: analytics failed status=${
            analyticsResponse.status
          } body=${await analyticsResponse.text()}`
        );
      }
    }

    if (settings.deep_research_enabled == null) {
      settings.deep_research_enabled = true;
    }

    return {
      settings,
      enterpriseSettings,
      customAnalyticsScript,
      webVersion: settings.version ?? getWebVersion(),
      webDomain: HOST_URL,
      appName: enterpriseSettings?.application_name?.trim() || "Onyx",
    };
  } catch (error) {
    console.error("fetchSettingsSS exception: ", error);
    return null;
  }
}
