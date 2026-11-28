import type { Skill, SkillsList } from "@/lib/skills/types";

export const SKILL_GROUPS = [
  "mine",
  "marketplace",
  "organization",
  "shared",
  "builtin",
] as const;

export type SkillGroup = (typeof SKILL_GROUPS)[number];

export type SkillStatusFilter = "all" | "on" | "off";

export type GroupedSkills = Record<SkillGroup, Skill[]>;

export interface SkillListOptions {
  userId: string | null;
  /** The built-ins that chat offers (`useChatBuiltInSkillIds`). */
  chatBuiltInIds: ReadonlySet<string>;
  query: string;
  status: SkillStatusFilter;
  locale: string;
}

export function skillGroup(skill: Skill, userId: string | null): SkillGroup {
  if (skill.source === "builtin") return "builtin";
  if (skill.marketplace?.kind === "github") return "marketplace";
  if (userId !== null && skill.owner?.id === userId) return "mine";
  if (skill.published_version_number !== null) return "organization";
  return "shared";
}

function visible(skill: Skill, chatBuiltInIds: ReadonlySet<string>): boolean {
  return skill.source === "custom"
    ? skill.member_visible
    : chatBuiltInIds.has(skill.id);
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

/** Most recently updated first, then by name. */
function compare(a: Skill, b: Skill, locale: string): number {
  return (
    (b.updated_at ?? "").localeCompare(a.updated_at ?? "") ||
    a.name.localeCompare(b.name, locale, { sensitivity: "base" })
  );
}

export function visibleSkills(
  list: SkillsList,
  chatBuiltInIds: ReadonlySet<string>
): Skill[] {
  return [...list.customs, ...list.builtins].filter((skill) =>
    visible(skill, chatBuiltInIds)
  );
}

export function groupSkills(
  list: SkillsList,
  options: SkillListOptions
): GroupedSkills {
  const groups: GroupedSkills = {
    mine: [],
    marketplace: [],
    organization: [],
    shared: [],
    builtin: [],
  };
  for (const skill of visibleSkills(list, options.chatBuiltInIds)) {
    if (matches(skill, options))
      groups[skillGroup(skill, options.userId)].push(skill);
  }
  for (const group of SKILL_GROUPS)
    groups[group].sort((a, b) => compare(a, b, options.locale));
  return groups;
}
