import { pluginSwitch, type MemberPluginEntry } from "@/lib/plugins/directory";
import type { SkillStatusFilter } from "@/lib/customize/skills";

export const PLUGIN_GROUPS = ["mine", "organization", "shared"] as const;

export type PluginGroup = (typeof PLUGIN_GROUPS)[number];

export interface GroupedPlugins {
  mine: MemberPluginEntry[];
  organization: MemberPluginEntry[];
  shared: MemberPluginEntry[];
}

export interface PluginListOptions {
  userEmail: string | null;
  query: string;
  status: SkillStatusFilter;
  locale: string;
}

/** The user's own plugins come first, as their skills do, published or not. */
export function pluginGroup(
  entry: MemberPluginEntry,
  userEmail: string | null
): PluginGroup {
  if (userEmail !== null && entry.ownerEmail === userEmail) return "mine";
  return entry.section;
}

function matches(
  entry: MemberPluginEntry,
  options: PluginListOptions
): boolean {
  const query = options.query.trim().toLocaleLowerCase(options.locale);
  return (
    (options.status === "all" ||
      pluginSwitch(entry).enabled === (options.status === "on")) &&
    (query === "" ||
      [
        entry.name,
        entry.description ?? "",
        ...entry.skills.map((skill) => skill.name),
        ...entry.integrations.map((integration) => integration.name),
      ]
        .join(" ")
        .toLocaleLowerCase(options.locale)
        .includes(query))
  );
}

export function groupPlugins(
  entries: readonly MemberPluginEntry[],
  options: PluginListOptions
): GroupedPlugins {
  const groups: GroupedPlugins = { mine: [], organization: [], shared: [] };
  for (const entry of entries)
    if (matches(entry, options))
      groups[pluginGroup(entry, options.userEmail)].push(entry);
  return groups;
}
