import { useUser } from "@/providers/UserProvider";
import { hasPermission } from "@/lib/permissions";
import { Permission } from "@/lib/types";

export interface PermissionAuthority {
  /** Holds the permission outright, or is an admin — unrestricted org-wide. */
  isGlobalHolder: boolean;
  /** Reaches it only through the group-manager bundle, so every write is bounded
   *  by GATE 2: non-public, and inside the groups they manage. */
  isScopedManager: boolean;
}

/**
 * Splits authority over `permission` into its two kinds.
 *
 * `permissions` carries global grants only; `adminCapabilities` adds the scoped
 * manager bundle. Holding the token in the second but not the first is what
 * makes someone scoped — a distinction `isAdmin` cannot express, since a global
 * holder is not an admin yet is unrestricted for that permission.
 *
 * Neither flag means no authority at all; both are false.
 */
export function usePermissionAuthority(
  permission: Permission
): PermissionAuthority {
  const { permissions, adminCapabilities } = useUser();

  const isGlobalHolder = hasPermission(permissions, permission);
  return {
    isGlobalHolder,
    isScopedManager:
      !isGlobalHolder && hasPermission(adminCapabilities, permission),
  };
}
