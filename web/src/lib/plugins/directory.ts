import type { CustomizePanel } from "@/lib/customize/paths";
import type { SkillMarketplace } from "@/lib/marketplaces/types";
import type { CustomSkill, Skill } from "@/lib/skills/types";

/** Where a plugin comes from: a GitHub marketplace, the Organization library,
 * the user's own uploads, a plugin that someone shared with the user, or a
 * private plugin of someone else that a plugin manager sees. */
export type PluginSection =
  | "marketplace"
  | "organization"
  | "mine"
  | "shared"
  | "private";

/** One plugin of the Customize pages. A custom skill's id is its plugin id. */
export interface MemberPluginEntry {
  id: string;
  name: string;
  description: string | null;
  section: PluginSection;
  ownerEmail: string | null;
  /** The GitHub marketplace that syncs the plugin. */
  marketplace: SkillMarketplace | null;
  /** The plugin's own row of the skill list. */
  skill: CustomSkill;
}

function pluginSection(
  skill: Skill,
  ownerEmail: string | null,
  userEmail: string | null
): PluginSection {
  if (skill.marketplace?.kind === "github") return "marketplace";
  if (skill.published_version_number !== null) return "organization";
  if (ownerEmail === null || ownerEmail === userEmail) return "mine";
  return skill.is_personal ? "private" : "shared";
}

function isCustomSkill(skill: Skill): skill is CustomSkill {
  return skill.source === "custom";
}

/** Whether a Customize panel lists the skill: the admin panel lists every
 * plugin, the member panel only the ones members can see. */
export function panelShowsSkill(skill: Skill, panel: CustomizePanel): boolean {
  return panel === "admin" || skill.member_visible;
}

/** The plugins of the custom skills, sorted by name. */
export function memberPluginEntries(
  skills: readonly Skill[],
  userEmail: string | null,
  locale: string
): MemberPluginEntry[] {
  return skills
    .filter(isCustomSkill)
    .map((skill): MemberPluginEntry => {
      const ownerEmail = skill.owner?.email ?? null;
      return {
        id: skill.id,
        name: skill.name,
        description: skill.description || null,
        section: pluginSection(skill, ownerEmail, userEmail),
        ownerEmail,
        marketplace:
          skill.marketplace?.kind === "github" ? skill.marketplace : null,
        skill,
      };
    })
    .sort((a, b) => a.name.localeCompare(b.name, locale));
}

/** Why the user cannot use the on/off switch of a plugin. */
export type PluginSwitchBlock = "required" | "unavailable";

export interface PluginSwitch {
  enabled: boolean;
  blocked: PluginSwitchBlock | null;
}

/** The user's on/off switch: the switch of the plugin's skill. */
export function pluginSwitch(entry: MemberPluginEntry): PluginSwitch {
  const { skill } = entry;
  return {
    enabled: skill.enabled,
    blocked: skill.can_toggle
      ? null
      : skill.required_for_user
        ? "required"
        : "unavailable",
  };
}
