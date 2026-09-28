import type { AccessType } from "@/lib/types";

// Perm sync plus a data-access group restriction (ENG-4342). The wire name is
// provisional until the connector editing initiative confirms it.
export const SYNC_RESTRICTED_ACCESS_TYPE =
  "sync_restricted" satisfies AccessType;

export function isPermSynced(accessType: AccessType): boolean {
  return accessType === "sync" || accessType === SYNC_RESTRICTED_ACCESS_TYPE;
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
