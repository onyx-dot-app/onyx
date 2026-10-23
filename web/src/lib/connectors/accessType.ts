import type { AccessType } from "@/lib/types";

// Perm sync, narrowed to members of the connector's data-access groups. The
// groups are sent as the create request's `data_access`.
export const SYNC_RESTRICTED_ACCESS_TYPE =
  "sync_restricted" satisfies AccessType;

export function isPermSynced(accessType: AccessType): boolean {
  return accessType === "sync" || accessType === SYNC_RESTRICTED_ACCESS_TYPE;
}

/** A manage group's role: Editors change and delete the configuration;
    Operators schedule and monitor indexing. */
export type ConnectorManageRole = "editor" | "operator";

export interface ManageAccessEntry {
  group_id: number;
  role: ConnectorManageRole;
}

// Who reads the documents (access_type, plus data_access_group_ids for
// private) and who manages the connector (groups, each with a role in
// group_roles; a group without one is an Editor).
export interface ConnectorAccessFormValues {
  access_type: AccessType;
  groups: number[];
  group_roles: Record<string, ConnectorManageRole>;
  data_access_group_ids: number[];
}

/** The manage groups with their roles, as the link request's `manage_access`. */
export function toManageAccess(
  groups: number[],
  roles: Record<string, ConnectorManageRole>
): ManageAccessEntry[] {
  return groups.map((id) => ({
    group_id: id,
    role: roles[String(id)] ?? "editor",
  }));
}

export interface ConnectorGroupRestrictionFormValues {
  restrict_access_to_groups: boolean;
  restriction_group_ids: number[];
}

export interface WireAccess {
  access_type: AccessType;
  restriction_group_ids: number[];
}

// The form keeps "sync" plus a restriction flag, so the dropdown never sees the
// fourth value. A switched-on restriction with no groups restricts nobody.
export function toWireAccess(
  accessType: AccessType,
  restriction: ConnectorGroupRestrictionFormValues
): WireAccess {
  const restricted =
    accessType === "sync" &&
    restriction.restrict_access_to_groups &&
    restriction.restriction_group_ids.length > 0;
  return restricted
    ? {
        access_type: SYNC_RESTRICTED_ACCESS_TYPE,
        restriction_group_ids: restriction.restriction_group_ids,
      }
    : { access_type: accessType, restriction_group_ids: [] };
}
