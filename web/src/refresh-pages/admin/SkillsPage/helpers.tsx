import type {
  CustomSkill,
  SkillVisibility,
} from "@/refresh-pages/admin/SkillsPage/interfaces";

export interface VisibilitySummary {
  label: string;
  description?: string;
}

export function summarizeVisibility(skill: CustomSkill): VisibilitySummary {
  switch (skill.visibility) {
    case "private":
      return { label: "Private" };
    case "users":
      return {
        label: "Users",
        description: `${skill.shared_user_count} ${
          skill.shared_user_count === 1 ? "user" : "users"
        }`,
      };
    case "groups":
      return {
        label: "Groups",
        description: `${skill.shared_group_count} ${
          skill.shared_group_count === 1 ? "group" : "groups"
        }`,
      };
    case "users_and_groups":
      return {
        label: "Shared",
        description: `${skill.shared_group_count} groups, ${skill.shared_user_count} users`,
      };
    case "org_wide":
      return {
        label: "Org-wide",
        description: skill.promoted_by_admin ? "Promoted by admin" : undefined,
      };
  }
}

export function visibilityToHuman(visibility: SkillVisibility): string {
  switch (visibility) {
    case "private":
      return "Private";
    case "users":
      return "Specific users";
    case "groups":
      return "Specific groups";
    case "users_and_groups":
      return "Users + groups";
    case "org_wide":
      return "Org-wide";
  }
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

export function formatRelativeTime(isoTimestamp: string): string {
  const then = new Date(isoTimestamp).getTime();
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

export function shortFingerprint(sha256: string): string {
  return sha256.slice(0, 12);
}
