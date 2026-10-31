import type { useTranslations } from "next-intl";
import type { UserGroup } from "@/lib/types";

export type GroupsTranslate = ReturnType<
  typeof useTranslations<"admin.groups">
>;

/** Whether this group is a system default group (Admin, Basic). */
export function isBuiltInGroup(group: UserGroup): boolean {
  return group.is_default;
}

// The two built-in groups the backend creates, keyed by their stored name.
const BUILT_IN_GROUP_KEYS = { Admin: "admin", Basic: "basic" } as const;

function builtInGroupKey(group: UserGroup) {
  if (
    !isBuiltInGroup(group) ||
    !Object.prototype.hasOwnProperty.call(BUILT_IN_GROUP_KEYS, group.name)
  ) {
    return undefined;
  }
  // SAFETY: the own-property check above proves the name is a key of the map.
  return BUILT_IN_GROUP_KEYS[group.name as keyof typeof BUILT_IN_GROUP_KEYS];
}

/** The group name as shown to the user. Built-in names are translated. */
export function displayGroupName(group: UserGroup, t: GroupsTranslate): string {
  const key = builtInGroupKey(group);
  return key ? t(`builtIn.${key}.name`) : group.name;
}

/**
 * Build the description line(s) shown beneath the group name.
 *
 * Built-in groups use a fixed label.
 * Custom groups list resource counts ("3 connectors · 2 document sets · 2 agents")
 * or fall back to "No private connectors / document sets / agents".
 */
export function buildGroupDescription(
  group: UserGroup,
  t: GroupsTranslate
): string {
  if (isBuiltInGroup(group)) {
    const key = builtInGroupKey(group);
    return key ? t(`builtIn.${key}.description`) : "";
  }

  const parts: string[] = [];
  if (group.cc_pairs.length > 0) {
    parts.push(
      t("card.resourceCounts.connectors", { count: group.cc_pairs.length })
    );
  }
  if (group.document_sets.length > 0) {
    parts.push(
      t("card.resourceCounts.documentSets", {
        count: group.document_sets.length,
      })
    );
  }
  if (group.personas.length > 0) {
    parts.push(
      t("card.resourceCounts.agents", { count: group.personas.length })
    );
  }

  if (parts.length === 0) return t("card.resourceCounts.noPrivateResources");
  // One pair message per join so translators own the separator and its order.
  return parts.reduce((first, rest) =>
    t("card.resourceCounts.joined", { first, rest })
  );
}

/** Format the member count badge, e.g. "306 Members" or "1 Member". */
export function formatMemberCount(count: number, t: GroupsTranslate): string {
  return t("card.memberCount", { count });
}
