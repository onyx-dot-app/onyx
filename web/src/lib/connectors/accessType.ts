import type { AccessType } from "@/lib/types";

// Perm sync, narrowed to members of the connector's data-access groups. The
// groups are sent as the create request's `data_access`.
export const SYNC_RESTRICTED_ACCESS_TYPE =
  "sync_restricted" satisfies AccessType;

export function isPermSynced(accessType: AccessType): boolean {
  return accessType === "sync" || accessType === SYNC_RESTRICTED_ACCESS_TYPE;
}

// Who reads the documents (access_type, plus data_access_group_ids for
// private) and who manages the connector (groups, as Editors).
export interface ConnectorAccessFormValues {
  access_type: AccessType;
  groups: number[];
  data_access_group_ids: number[];
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
