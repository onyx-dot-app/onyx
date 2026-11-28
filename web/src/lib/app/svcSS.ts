import type { Metadata } from "next";
import { fetchEnterpriseSettingsSS } from "@/lib/settings/svcSS";
import { buildUrl } from "@/lib/utilsSS";

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
  return `Admin | ${await fetchAppName()}`;
}

/** The backend's version, from its `/version` route; `null` when it fails. */
export async function getBackendVersion(): Promise<string | null> {
  try {
    const res = await fetch(buildUrl("/version"));
    if (!res.ok) {
      return null;
    }
    const data: { backend_version: string } = await res.json();
    return data.backend_version;
  } catch (e) {
    console.log(`Error fetching backend version info: ${e}`);
    return null;
  }
}
