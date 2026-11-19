export const CUSTOMIZE_TABS = ["plugins", "skills", "integrations"] as const;

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

export function skillEditHref(
  skillId: string
): `/app/customize/skills/${string}` {
  return `/app/customize/skills/${skillId}?edit=1`;
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

export function parsePluginPageTab(value: string | null): PluginPageTab {
  return value === "skills" || value === "integrations" || value === "versions"
    ? value
    : "overview";
}
