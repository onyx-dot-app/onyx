import type { UserGroup } from "@/lib/types";

/** Whether this group is a system default group (Admin, Basic). */
export function isBuiltInGroup(group: UserGroup): boolean {
  return group.is_default;
}

/** Human-readable description for built-in groups. */
const BUILT_IN_DESCRIPTIONS: Record<string, string> = {
  Basic: "所有用户默认加入的基础权限用户组。",
  Admin: "内置管理员用户组，拥有管理全部权限的访问能力。",
};

/**
 * Build the description line(s) shown beneath the group name.
 *
 * Built-in groups use a fixed label.
 * Custom groups list resource counts ("3 connectors · 2 document sets · 2 agents")
 * or fall back to "No private connectors / document sets / agents".
 */
export function buildGroupDescription(group: UserGroup): string {
  if (isBuiltInGroup(group)) {
    return BUILT_IN_DESCRIPTIONS[group.name] ?? "";
  }

  const parts: string[] = [];
  if (group.cc_pairs.length > 0) {
    parts.push(`${group.cc_pairs.length} 个连接器`);
  }
  if (group.document_sets.length > 0) {
    parts.push(`${group.document_sets.length} 个文档集`);
  }
  if (group.personas.length > 0) {
    parts.push(`${group.personas.length} 个智能体`);
  }

  return parts.length > 0 ? parts.join(" · ") : "暂无私有连接器 / 文档集 / 智能体";
}

/** Format the member count badge, e.g. "306 Members" or "1 Member". */
export function formatMemberCount(count: number): string {
  return `${count} 位成员`;
}
