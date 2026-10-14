import type { Metadata } from "next";
import { fetchEnterpriseSettingsSS } from "@/lib/settings/svcSS";

/** Server-side twin of useSettings().appName for server components. */
export async function fetchAppName(): Promise<string> {
  const enterprise = await fetchEnterpriseSettingsSS();
  return enterprise?.application_name?.trim() || "Onyx";
}

export async function generateFaviconMetadata(): Promise<Metadata["icons"]> {
  const enterprise = await fetchEnterpriseSettingsSS();
  return {
    icon: enterprise?.use_custom_logo
      ? "/api/enterprise-settings/logo"
      : "/onyx.ico",
  };
}

export async function generateAdminTitleMetadata(): Promise<Metadata["title"]> {
  return `Admin — ${await fetchAppName()}`;
}
