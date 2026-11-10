import type { CustomSkill, Skill } from "@/lib/skills/types";

export function canShareSkill({ skill }: { skill: CustomSkill }): boolean {
  if (skill.retired_at) return false;
  if (skill.marketplace) return skill.marketplace.can_share;
  return (
    skill.user_permission === "OWNER" || skill.user_permission === "EDITOR"
  );
}

export function canDeleteSkill({
  skill,
  canManageCompanySkills,
}: {
  skill: CustomSkill;
  canManageCompanySkills: boolean;
}): boolean {
  if (skill.retired_at) {
    return skill.user_permission === "OWNER" || canManageCompanySkills;
  }
  if (skill.marketplace) return false;
  return (
    (skill.user_permission === "OWNER" || skill.user_permission === "EDITOR") &&
    (canManageCompanySkills ||
      (skill.installation_policy !== "REQUIRED" &&
        !skill.group_shares.some(
          ({ installation_policy }) => installation_policy === "REQUIRED"
        )))
  );
}

export function canReadSkillHistory(skill: Skill): boolean {
  return (
    skill.source === "custom" &&
    !skill.retired_at &&
    (skill.user_permission === "OWNER" || skill.user_permission === "EDITOR")
  );
}
