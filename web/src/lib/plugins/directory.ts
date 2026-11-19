import type { CustomSkill, Skill } from "@/lib/skills/types";

/** Where a plugin sits: the Organization library, the user's own uploads, or
 * a personal plugin of someone else that the user can see. */
export type PluginSection = "organization" | "mine" | "shared";

/** One plugin of the Customize pages. A plugin holds custom skills; a custom
 * skill's id is its plugin id. */
export interface MemberPluginEntry {
  id: string;
  name: string;
  description: string | null;
  section: PluginSection;
  ownerEmail: string | null;
  skills: CustomSkill[];
}

function isCustomSkill(skill: Skill): skill is CustomSkill {
  return skill.source === "custom";
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
        section:
          skill.published_version_number !== null
            ? "organization"
            : ownerEmail === null || ownerEmail === userEmail
              ? "mine"
              : "shared",
        ownerEmail,
        skills: [skill],
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
  const skill = entry.skills[0];
  if (!skill) return { enabled: false, blocked: "unavailable" };
  return {
    enabled: skill.enabled,
    blocked: skill.can_toggle
      ? null
      : skill.required_for_user
        ? "required"
        : "unavailable",
  };
}
