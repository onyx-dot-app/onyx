import { useUser } from "@/providers/UserProvider";
import { hasPermission } from "@/lib/permissions";
import { Permission } from "@/lib/types";

export interface ConnectorAuthority {
  /** Holds MANAGE_CONNECTORS outright (or is an admin) — unrestricted org-wide. */
  isGlobalHolder: boolean;
  /** Reaches connectors only through the group-manager bundle, so every write is
   *  bounded by GATE 2: non-public, and inside the groups they manage. */
  isScopedManager: boolean;
}

/**
 * Splits MANAGE_CONNECTORS authority into its two kinds.
 *
 * `permissions` carries global grants only; `adminCapabilities` adds the scoped
 * manager bundle. Holding the token in the second but not the first is what
 * makes someone scoped — the distinction admin-vs-not cannot express, since a
 * global holder is not an admin yet is unrestricted for connectors.
 */
export function useConnectorAuthority(): ConnectorAuthority {
  const { permissions, adminCapabilities } = useUser();

  const isGlobalHolder = hasPermission(
    permissions,
    Permission.MANAGE_CONNECTORS
  );
  return {
    isGlobalHolder,
    isScopedManager:
      !isGlobalHolder &&
      hasPermission(adminCapabilities, Permission.MANAGE_CONNECTORS),
  };
}
