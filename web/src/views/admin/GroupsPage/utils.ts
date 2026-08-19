import type { UserGroup } from "@/lib/types";

/** Whether this group is a system default group (Admin, Basic). */
export function isBuiltInGroup(group: UserGroup): boolean {
  return group.is_default;
}

/** Human-readable description for built-in groups. */
const BUILT_IN_DESCRIPTIONS: Record<string, string> = {
  Basic: "Default group for all users with basic permissions.",
  Admin: "Built-in admin group with full access to manage all permissions.",
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
    parts.push(
      `${group.cc_pairs.length} connector${
        group.cc_pairs.length !== 1 ? "s" : ""
      }`
    );
  }
  if (group.document_sets.length > 0) {
    parts.push(
      `${group.document_sets.length} document set${
        group.document_sets.length !== 1 ? "s" : ""
      }`
    );
  }
  if (group.personas.length > 0) {
    parts.push(
      `${group.personas.length} agent${group.personas.length !== 1 ? "s" : ""}`
    );
  }

  return parts.length > 0
    ? parts.join(" · ")
    : "No private connectors / document sets / agents";
}

/** Format the member count badge, e.g. "306 Members" or "1 Member". */
export function formatMemberCount(count: number): string {
  return `${count} ${count === 1 ? "Member" : "Members"}`;
}
