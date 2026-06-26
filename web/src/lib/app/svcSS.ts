import type { Metadata } from "next";
import { SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED } from "@/lib/constants";
import { fetchEnterpriseSettingsSS } from "@/lib/settings/svcSS";

async function fetchAppName(): Promise<string> {
  if (SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED) {
    const enterprise = await fetchEnterpriseSettingsSS();
    if (enterprise?.application_name?.trim()) {
      return enterprise.application_name.trim();
    }
  }
  return "Onyx";
}

export async function generateFaviconMetadata(): Promise<Metadata["icons"]> {
  let iconSrc = "/onyx.ico";

  if (SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED) {
    const enterprise = await fetchEnterpriseSettingsSS();
    if (enterprise?.use_custom_logo) {
      iconSrc = "/api/enterprise-settings/logo";
    }
  }

  return { icon: iconSrc };
}

export async function generateAdminTitleMetadata(): Promise<Metadata["title"]> {
  return `Admin — ${await fetchAppName()}`;
}
