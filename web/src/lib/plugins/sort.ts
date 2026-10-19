import type { InstalledPlugin, PluginReference } from "@/lib/plugins/types";
import type { MemberPlugin } from "@/lib/plugins/member";

export const MEMBER_PLUGIN_SURFACES = ["chat", "agents", "craft"] as const;
export type MemberPluginSurface = (typeof MEMBER_PLUGIN_SURFACES)[number];

export type PluginStatus = "active" | "issues" | "inactive";

const kindOrder = { mcp: 0, openapi: 1, "external-app": 2 };
const statusOrder = { active: 0, issues: 1, inactive: 2 };

export function sortPlugins<T extends { kind: PluginReference["kind"] }>(
  plugins: readonly T[],
  getStatus: (plugin: T) => PluginStatus,
  getName: (plugin: T) => string,
  locale: string
): T[] {
  const collator = new Intl.Collator(locale, {
    sensitivity: "base",
    numeric: true,
  });
  return [...plugins].sort(
    (a, b) =>
      statusOrder[getStatus(a)] - statusOrder[getStatus(b)] ||
      kindOrder[a.kind] - kindOrder[b.kind] ||
      collator.compare(getName(a), getName(b))
  );
}

export function installedPluginStatus(
  plugin: InstalledPlugin,
  craftAvailable: boolean
): PluginStatus {
  const enabled =
    plugin.kind === "external-app"
      ? plugin.app.enabled
      : plugin.kind === "openapi"
        ? plugin.tool.enabled
        : plugin.server.default_chat_enabled ||
          (craftAvailable && plugin.server.available_in_craft);
  return enabled ? "active" : "inactive";
}

export function memberPluginSurfaceAvailability(
  plugin: MemberPlugin,
  surface: MemberPluginSurface,
  craftAvailable = true
) {
  const supported =
    surface === "craft"
      ? craftAvailable && plugin.kind !== "openapi"
      : plugin.kind !== "external-app";
  if (!supported)
    return { supported, available: false, personallyEnabled: true };
  if (plugin.kind === "external-app")
    return { supported, available: true, personallyEnabled: true };
  if (surface === "agents")
    return {
      supported,
      available: plugin.kind === "mcp" || plugin.tool.enabled,
      personallyEnabled: true,
    };
  const available =
    plugin.kind === "mcp"
      ? surface === "chat"
        ? plugin.server.default_chat_enabled
        : plugin.server.available_in_craft
      : plugin.tool.enabled && plugin.tool.default_chat_enabled;
  const personallyEnabled =
    plugin.kind === "mcp"
      ? surface === "chat"
        ? plugin.server.user_enabled_in_chat
        : plugin.server.user_enabled_in_craft
      : plugin.tool.user_enabled_in_chat;
  return { supported, available, personallyEnabled };
}

export function memberPluginSurfaceStatus(
  plugin: MemberPlugin,
  surface: MemberPluginSurface,
  hasSkillIssues = false,
  craftAvailable = true
): PluginStatus {
  const { supported, available, personallyEnabled } =
    memberPluginSurfaceAvailability(plugin, surface, craftAvailable);
  if (!supported) return "inactive";
  if (plugin.connection.kind !== "connected") {
    return plugin.connection.kind === "oauth" ||
      plugin.connection.kind === "credentials"
      ? "issues"
      : "inactive";
  }
  if (plugin.kind === "external-app")
    return hasSkillIssues ? "issues" : "active";
  if (available === false || personallyEnabled === false) return "issues";
  return available === true ? "active" : "inactive";
}

export function memberPluginStatus(
  plugin: MemberPlugin,
  hasSkillIssues = false,
  craftAvailable = false
): PluginStatus {
  const statuses = MEMBER_PLUGIN_SURFACES.filter(
    (item) =>
      memberPluginSurfaceAvailability(plugin, item, craftAvailable).supported
  ).map((item) =>
    memberPluginSurfaceStatus(plugin, item, hasSkillIssues, craftAvailable)
  );
  return statuses.includes("issues")
    ? "issues"
    : statuses.length > 0 && statuses.every((status) => status === "active")
      ? "active"
      : "inactive";
}
