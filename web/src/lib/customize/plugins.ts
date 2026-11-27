import { pluginSwitch, type MemberPluginEntry } from "@/lib/plugins/directory";
import type { SkillStatusFilter } from "@/lib/customize/skills";

export const PLUGIN_GROUPS = [
  "mine",
  "marketplace",
  "organization",
  "shared",
  "private",
] as const;

export type PluginGroup = (typeof PLUGIN_GROUPS)[number];

export type GroupedPlugins = Record<PluginGroup, MemberPluginEntry[]>;

export interface PluginListOptions {
  userEmail: string | null;
  query: string;
  status: SkillStatusFilter;
  locale: string;
}

/** The user's own plugins come first, as their skills do, published or not.
 * A plugin from a marketplace always shows its marketplace. */
export function pluginGroup(
  entry: MemberPluginEntry,
  userEmail: string | null
): PluginGroup {
  if (entry.section === "marketplace") return "marketplace";
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
        entry.ownerEmail ?? "",
        entry.marketplace?.name ?? "",
        ...entry.skills.flatMap((skill) =>
          skill.group_summaries.map((summary) => summary.group_name)
        ),
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
  const groups: GroupedPlugins = {
    mine: [],
    marketplace: [],
    organization: [],
    shared: [],
    private: [],
  };
  for (const entry of entries)
    if (matches(entry, options))
      groups[pluginGroup(entry, options.userEmail)].push(entry);
  return groups;
}
