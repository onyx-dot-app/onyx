export const CUSTOMIZE_TABS = ["skills", "integrations", "plugins"] as const;

export type CustomizeTab = (typeof CUSTOMIZE_TABS)[number];

export const CUSTOMIZE_PATH = "/app/customize";

export function customizeTabHref(
  tab: CustomizeTab
): `/app/customize/${CustomizeTab}` {
  return `/app/customize/${tab}`;
}

export function skillHref(skillId: string): `/app/customize/skills/${string}` {
  return `/app/customize/skills/${skillId}`;
}

export function adminSkillHref(skillId: string): `/admin/skills/${string}` {
  return `/admin/skills/${skillId}`;
}

export function newSkillHref(
  draftId?: string
): `/app/customize/skills/new${string}` {
  return draftId
    ? `/app/customize/skills/new?draft=${encodeURIComponent(draftId)}`
    : "/app/customize/skills/new";
}

export type PluginPageTab = "overview" | "skills" | "integrations" | "versions";

export function pluginHref(
  pluginId: string,
  tab?: PluginPageTab
): `/app/customize/plugins/${string}` {
  return tab && tab !== "overview"
    ? `/app/customize/plugins/${pluginId}?tab=${tab}`
    : `/app/customize/plugins/${pluginId}`;
}

export const MARKETPLACES_PATH = "/app/customize/plugins/marketplaces";

export function parsePluginPageTab(value: string | null): PluginPageTab {
  return value === "skills" || value === "integrations" || value === "versions"
    ? value
    : "overview";
}

export type IntegrationPageTab = "overview" | "configuration" | "actions";

export function integrationHref(
  integrationId: number,
  tab?: IntegrationPageTab
): `/app/customize/integrations/${string}` {
  return tab && tab !== "overview"
    ? `/app/customize/integrations/${integrationId}?tab=${tab}`
    : `/app/customize/integrations/${integrationId}`;
}

export const NEW_INTEGRATION_PATH = "/app/customize/integrations/new";

export type PluginPagePath = `/app/customize/plugins/${string}`;

export function isPluginPagePath(path: string): path is PluginPagePath {
  return path.startsWith("/app/customize/plugins/");
}
const ADMIN_NEW_INTEGRATION_PATH = "/admin/integrations/new";

export interface NewIntegrationPrefill {
  name: string;
  serverUrl: string;
  transport: "STREAMABLE_HTTP" | "SSE";
  /** Preset the owner to the organization (admin page only). */
  forOrganization?: boolean;
  /** The plugin page to open after the save: the plugin that needs it. */
  returnTo?: PluginPagePath;
}

/** The add page with the fields filled in. `admin` opens the admin page,
 * where the owner can be the organization. */
export function newIntegrationHref(
  prefill: NewIntegrationPrefill,
  admin = false
):
  | `/app/customize/integrations/new?${string}`
  | `/admin/integrations/new?${string}` {
  const params = new URLSearchParams({
    name: prefill.name,
    server_url: prefill.serverUrl,
    transport: prefill.transport,
  });
  if (prefill.forOrganization) params.set("owner", "organization");
  if (prefill.returnTo) params.set("return_to", prefill.returnTo);
  return admin
    ? `${ADMIN_NEW_INTEGRATION_PATH}?${params.toString()}`
    : `${NEW_INTEGRATION_PATH}?${params.toString()}`;
}

export function parseNewIntegrationPrefill(
  params: Pick<URLSearchParams, "get">
): NewIntegrationPrefill | null {
  const name = params.get("name");
  const serverUrl = params.get("server_url");
  if (!name || !serverUrl) return null;
  const returnTo = params.get("return_to");
  return {
    name,
    serverUrl,
    transport: params.get("transport") === "SSE" ? "SSE" : "STREAMABLE_HTTP",
    forOrganization: params.get("owner") === "organization",
    // Only a plugin page, so the link cannot send the user to another site.
    returnTo: returnTo && isPluginPagePath(returnTo) ? returnTo : undefined,
  };
}
