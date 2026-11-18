import { ADMIN_ROUTES } from "@/lib/admin-routes";
import type {
  AdminIntegration,
  AdminPluginEntry,
  PolicyValue,
} from "@/lib/integrations/types";

export type IntegrationDetailTab = "overview" | "configuration" | "actions";

export function parseIntegrationTab(
  value: string | null
): IntegrationDetailTab {
  return value === "configuration" || value === "actions" ? value : "overview";
}

export function integrationDetailHref(
  id: number,
  tab?: IntegrationDetailTab
): `/admin/integrations/${number}` | `/admin/integrations/${number}?${string}` {
  const path: `/admin/integrations/${number}` = `${ADMIN_ROUTES.INTEGRATIONS.path}/${id}`;
  return tab && tab !== "overview" ? `${path}?tab=${tab}` : path;
}

export function parsePositiveId(value: string | undefined): number | null {
  if (!value || !/^\d+$/.test(value)) return null;
  const id = Number(value);
  return Number.isSafeInteger(id) && id > 0 ? id : null;
}

export function pluginsFromIntegrations(
  integrations: AdminIntegration[],
  locale: string
): AdminPluginEntry[] {
  const entries = new Map<string, AdminPluginEntry>();
  for (const integration of integrations) {
    for (const plugin of integration.plugins) {
      const entry = entries.get(plugin.plugin_id);
      if (entry) entry.integrations.push(integration);
      else
        entries.set(plugin.plugin_id, { plugin, integrations: [integration] });
    }
  }
  return [...entries.values()].sort((a, b) =>
    a.plugin.plugin_name.localeCompare(b.plugin.plugin_name, locale)
  );
}

export function sortIntegrations(
  integrations: AdminIntegration[],
  locale: string
): AdminIntegration[] {
  return [...integrations].sort(
    (a, b) =>
      Number(b.needs_setup) - Number(a.needs_setup) ||
      a.name.localeCompare(b.name, locale)
  );
}
