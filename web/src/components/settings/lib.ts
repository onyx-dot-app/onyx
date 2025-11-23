import {
  CombinedSettings,
  EnterpriseSettings,
  ApplicationStatus,
  Settings,
  QueryHistoryType,
} from "@/app/admin/settings/interfaces";
import {
  CUSTOM_ANALYTICS_ENABLED,
  HOST_URL,
  SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED,
} from "@/lib/constants";
import { fetchSS } from "@/lib/utilsSS";
import { getWebVersion } from "@/lib/version";

export enum SettingsError {
  OTHER = "OTHER",
}

/**
 * Default Enterprise Settings to use when the backend endpoint is not available
 * or when Enterprise Edition is enabled but backend hasn't been configured yet
 */
function getDefaultEnterpriseSettings(): EnterpriseSettings {
  return {
    application_name: "Dom Engin.",
    use_custom_logo: false,
    use_custom_logotype: false,
    custom_nav_items: [],
    custom_lower_disclaimer_content: null,
    custom_header_content: null,
    two_lines_for_chat_header: null,
    custom_popup_header: null,
    custom_popup_content: null,
    enable_consent_screen: null,
  };
}

export async function fetchStandardSettingsSS() {
  return fetchSS("/settings");
}

export async function fetchEnterpriseSettingsSS() {
  return fetchSS("/enterprise-settings");
}

export async function fetchCustomAnalyticsScriptSS() {
  return fetchSS("/enterprise-settings/custom-analytics-script");
}

export async function fetchSettingsSS(): Promise<CombinedSettings | null> {
  const tasks = [fetchStandardSettingsSS()];
  if (SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED) {
    tasks.push(fetchEnterpriseSettingsSS());
    if (CUSTOM_ANALYTICS_ENABLED) {
      tasks.push(fetchCustomAnalyticsScriptSS());
    }
  }

  try {
    const results = await Promise.all(tasks);

    let settings: Settings;

    const result_0 = results[0];
    if (!result_0) {
      throw new Error("Standard settings fetch failed.");
    }

    if (!result_0.ok) {
      if (result_0.status === 403 || result_0.status === 401) {
        settings = {
          auto_scroll: true,
          application_status: ApplicationStatus.ACTIVE,
          gpu_enabled: false,
          maximum_chat_retention_days: null,
          notifications: [],
          needs_reindexing: false,
          anonymous_user_enabled: false,
          deep_research_enabled: true,
          temperature_override_enabled: true,
          query_history_type: QueryHistoryType.NORMAL,
        };
      } else {
        throw new Error(
          `fetchStandardSettingsSS failed: status=${
            result_0.status
          } body=${await result_0.text()}`
        );
      }
    } else {
      settings = await result_0.json();
    }

    let enterpriseSettings: EnterpriseSettings | null = null;
    if (tasks.length > 1) {
      const result_1 = results[1];
      if (!result_1) {
        // If fetch failed completely, use default settings
        enterpriseSettings = getDefaultEnterpriseSettings();
      } else if (!result_1.ok) {
        // 404 means the endpoint doesn't exist (backend not in EE mode)
        // 403/401 means unauthorized (user not authenticated)
        // In all cases, use default enterprise settings when EE is enabled
        if (result_1.status === 404) {
          console.warn(
            "Enterprise settings endpoint not found (404). Using default Enterprise settings."
          );
        } else if (result_1.status !== 403 && result_1.status !== 401) {
          // For other errors (500, etc.), log but use defaults
          console.error(
            `fetchEnterpriseSettingsSS failed: status=${
              result_1.status
            } body=${await result_1.text()}. Using default Enterprise settings.`
          );
        }
        // Use default settings when endpoint is not available
        enterpriseSettings = getDefaultEnterpriseSettings();
      } else {
        enterpriseSettings = await result_1.json();
      }
    } else if (SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED) {
      // If Enterprise is enabled but we didn't try to fetch (shouldn't happen, but safety check)
      enterpriseSettings = getDefaultEnterpriseSettings();
    }

    let customAnalyticsScript: string | null = null;
    if (tasks.length > 2) {
      const result_2 = results[2];
      if (!result_2) {
        throw new Error("fetchCustomAnalyticsScriptSS failed.");
      }

      if (!result_2.ok) {
        // 404 means the endpoint doesn't exist (backend not in EE mode)
        // 403 means unauthorized
        // In both cases, we continue with customAnalyticsScript = null
        if (result_2.status === 404) {
          console.warn(
            "Custom analytics script endpoint not found (404). Backend may not have Enterprise Edition enabled."
          );
        } else if (result_2.status !== 403) {
          // For other errors (500, etc.), log but don't fail the app
          console.error(
            `fetchCustomAnalyticsScriptSS failed: status=${
              result_2.status
            } body=${await result_2.text()}`
          );
        }
        // Continue with customAnalyticsScript = null
      } else {
        customAnalyticsScript = await result_2.json();
      }
    }

    if (settings.deep_research_enabled == null) {
      settings.deep_research_enabled = true;
    }

    const webVersion = getWebVersion();

    const combinedSettings: CombinedSettings = {
      settings,
      enterpriseSettings,
      customAnalyticsScript,
      webVersion,
      webDomain: HOST_URL,
    };

    return combinedSettings;
  } catch (error) {
    console.error("fetchSettingsSS exception: ", error);
    return null;
  }
}
