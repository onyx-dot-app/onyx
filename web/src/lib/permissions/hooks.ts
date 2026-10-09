import { useUser } from "@/providers/UserProvider";
import { hasPermission } from "@/lib/permissions";
import { Permission } from "@/lib/types";
import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { Tier } from "@/lib/settings/types";

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

/**
 * Mirrors the backend BUSINESS gate on `/manage/admin/user-group`. Gate edit
 * affordances on this, not `settings.enterprise` — that only means "EE build",
 * and below Business the endpoint 402s.
 */
export function useCanManageGroups(): boolean {
  return useTierAtLeast(Tier.BUSINESS);
}
