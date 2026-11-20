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

export function pluginHref(
  pluginId: string
): `/app/customize/plugins/${string}` {
  return `/app/customize/plugins/${pluginId}`;
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
