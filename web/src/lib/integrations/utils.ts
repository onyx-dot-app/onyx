import type { ActionPolicy } from "@/app/craft/v1/apps/registry";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import type {
  AdminIntegration,
  AdminPluginEntry,
  PolicyValue,
} from "@/lib/integrations/types";

const TO_ACTION_POLICY = {
  allow: "ALWAYS",
  ask: "ASK",
  blocked: "DENY",
} as const satisfies Record<PolicyValue, ActionPolicy>;

const FROM_ACTION_POLICY = {
  ALWAYS: "allow",
  ASK: "ask",
  DENY: "blocked",
} as const satisfies Record<ActionPolicy, PolicyValue>;

/** The policy components use the old values; the integration API uses these. */
export function toActionPolicy(value: PolicyValue): ActionPolicy {
  return TO_ACTION_POLICY[value];
}

export function fromActionPolicy(value: ActionPolicy): PolicyValue {
  return FROM_ACTION_POLICY[value];
}

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

export function parseIntegrationId(value: string | undefined): number | null {
  if (!value || !/^\d+$/.test(value)) return null;
  const id = Number(value);
  return Number.isSafeInteger(id) && id > 0 ? id : null;
}

/** The plugins that hold integrations, each with the integrations it holds. */
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

/** Integrations that ask for setup first, then by name. */
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
