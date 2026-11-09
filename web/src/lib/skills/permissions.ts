import type { CustomSkill } from "@/lib/skills/types";

export function canShareSkill({
  skill,
  canManageCompanySkills,
}: {
  skill: CustomSkill;
  canManageCompanySkills: boolean;
}): boolean {
  if (skill.retired_at) return false;
  if (skill.marketplace?.personal && skill.user_permission !== "OWNER") {
    return skill.user_permission === "EDITOR" && canManageCompanySkills;
  }
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
    (skill.installation_policy !== "REQUIRED" || canManageCompanySkills)
  );
}
