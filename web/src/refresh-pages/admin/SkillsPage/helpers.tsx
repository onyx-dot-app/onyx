import type {
  CustomSkill,
  SkillVisibility,
} from "@/refresh-pages/admin/SkillsPage/interfaces";

export interface VisibilitySummary {
  label: string;
  description?: string;
}

/**
 * Derive the UI visibility tri-state from the API's
 * (is_public, granted_group_ids) tuple.
 */
export function visibilityFromSkill(skill: CustomSkill): SkillVisibility {
  if (skill.is_public) return "org_wide";
  if (skill.granted_group_ids.length > 0) return "groups";
  return "private";
}

export function summarizeVisibility(skill: CustomSkill): VisibilitySummary {
  if (skill.is_personal) {
    return {
      label: "Personal",
      description: skill.author_email ?? undefined,
    };
  }
  const visibility = visibilityFromSkill(skill);
  switch (visibility) {
    case "private":
      return { label: "Private" };
    case "groups": {
      const n = skill.granted_group_ids.length;
      return {
        label: "Groups",
        description: `${n} ${n === 1 ? "group" : "groups"}`,
      };
    }
    case "org_wide":
      return { label: "Org-wide" };
  }
}

export function formatRelativeTime(isoTimestamp: string | null): string {
  if (!isoTimestamp) return "—";
  const then = new Date(isoTimestamp).getTime();
  if (Number.isNaN(then)) return "—";
  const now = Date.now();
  const diffMs = now - then;
  const diffMin = Math.round(diffMs / 60_000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.round(diffHr / 24);
  if (diffDay < 30) return `${diffDay}d ago`;
  const diffMo = Math.round(diffDay / 30);
  if (diffMo < 12) return `${diffMo}mo ago`;
  return `${Math.round(diffMo / 12)}y ago`;
}
