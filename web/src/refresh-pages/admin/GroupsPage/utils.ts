import type { UserGroup } from "@/lib/types";

/** Whether this group is a system default group (Admin, Basic). */
export function isBuiltInGroup(group: UserGroup): boolean {
  return group.is_default;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type TranslateFn = (key: string, params?: Record<string, any>) => string;

/**
 * Build the description line(s) shown beneath the group name.
 *
 * Built-in groups use a fixed label.
 * Custom groups list resource counts ("3 connectors · 2 document sets · 2 agents")
 * or fall back to "No private connectors / document sets / agents".
 */
export function buildGroupDescription(
  group: UserGroup,
  t: TranslateFn
): string {
  if (isBuiltInGroup(group)) {
    if (group.name === "Basic") return t("basicGroupDescription");
    if (group.name === "Admin") return t("adminGroupDescription");
    return "";
  }

  const parts: string[] = [];
  if (group.cc_pairs.length > 0) {
    parts.push(
      t("connectorCount", { count: group.cc_pairs.length })
    );
  }
  if (group.document_sets.length > 0) {
    parts.push(
      t("documentSetCount", { count: group.document_sets.length })
    );
  }
  if (group.personas.length > 0) {
    parts.push(t("agentCount", { count: group.personas.length }));
  }

  return parts.length > 0
    ? parts.join(" · ")
    : t("noPrivateResources");
}

/** Format the member count badge, e.g. "306 Members" or "1 Member". */
export function formatMemberCount(
  count: number,
  t: TranslateFn
): string {
  return `${count} ${count === 1 ? t("member") : t("members")}`;
}
