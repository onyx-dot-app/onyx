import type { Skill, SkillsList } from "@/lib/skills/types";

export const SKILL_GROUPS = [
  "mine",
  "organization",
  "shared",
  "builtin",
] as const;

export type SkillGroup = (typeof SKILL_GROUPS)[number];

export type SkillStatusFilter = "all" | "on" | "off";

export type SkillSort = "updated" | "name";

export interface GroupedSkills {
  mine: Skill[];
  organization: Skill[];
  shared: Skill[];
  builtin: Skill[];
}

export interface SkillListOptions {
  userId: string | null;
  /** Built-in skills need the Craft sandbox, as `list_chat_skills` says. */
  craftEnabled: boolean;
  query: string;
  status: SkillStatusFilter;
  sort: SkillSort;
  locale: string;
}

export function skillGroup(skill: Skill, userId: string | null): SkillGroup {
  if (skill.source === "builtin") return "builtin";
  if (userId !== null && skill.owner?.id === userId) return "mine";
  if (skill.published_version_number !== null) return "organization";
  return "shared";
}

function visible(skill: Skill, craftEnabled: boolean): boolean {
  return skill.source === "custom"
    ? true
    : craftEnabled && skill.is_available !== null;
}

function matches(skill: Skill, options: SkillListOptions): boolean {
  const query = options.query.trim().toLocaleLowerCase(options.locale);
  return (
    (options.status === "all" || skill.enabled === (options.status === "on")) &&
    (query === "" ||
      `${skill.name} ${skill.description}`
        .toLocaleLowerCase(options.locale)
        .includes(query))
  );
}

function compare(a: Skill, b: Skill, options: SkillListOptions): number {
  const byName = a.name.localeCompare(b.name, options.locale, {
    sensitivity: "base",
  });
  if (options.sort === "name") return byName;
  return (b.updated_at ?? "").localeCompare(a.updated_at ?? "") || byName;
}

export function visibleSkills(
  list: SkillsList,
  craftEnabled: boolean
): Skill[] {
  return [...list.customs, ...list.builtins].filter((skill) =>
    visible(skill, craftEnabled)
  );
}

export function groupSkills(
  list: SkillsList,
  options: SkillListOptions
): GroupedSkills {
  const groups: GroupedSkills = {
    mine: [],
    organization: [],
    shared: [],
    builtin: [],
  };
  for (const skill of visibleSkills(list, options.craftEnabled)) {
    if (matches(skill, options))
      groups[skillGroup(skill, options.userId)].push(skill);
  }
  for (const group of SKILL_GROUPS)
    groups[group].sort((a, b) => compare(a, b, options));
  return groups;
}
