import type { UserGroup } from "@/lib/types";
import i18n from "@/lib/i18n";

/** Whether this group is a system default group (Admin, Basic). */
export function isBuiltInGroup(group: UserGroup): boolean {
  return group.is_default;
}

/** Translation keys for built-in group descriptions. */
const BUILT_IN_DESCRIPTION_KEYS: Record<string, string> = {
  Basic: "admin.groups.desc_basic",
  Admin: "admin.groups.desc_admin",
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
    const key = BUILT_IN_DESCRIPTION_KEYS[group.name];
    return key ? i18n.t(key) : "";
  }

  const parts: string[] = [];
  if (group.cc_pairs.length > 0) {
    parts.push(
      i18n.t("admin.groups.count_connectors", { count: group.cc_pairs.length })
    );
  }
  if (group.document_sets.length > 0) {
    parts.push(
      i18n.t("admin.groups.count_document_sets", {
        count: group.document_sets.length,
      })
    );
  }
  if (group.personas.length > 0) {
    parts.push(
      i18n.t("admin.groups.count_agents", { count: group.personas.length })
    );
  }

  return parts.length > 0
    ? parts.join(" · ")
    : i18n.t("admin.groups.no_private_resources");
}

/** Format the member count badge, e.g. "306 Members" or "1 Member". */
export function formatMemberCount(count: number): string {
  return i18n.t("admin.groups.member_count", { count });
}
