import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { Permission, User } from "@/lib/types";

// Tokens a group manager may exercise, scoped to the groups they manage — mirrors
// the backend SCOPED_MANAGER_PERMISSIONS bundle. (MANAGE_SKILLS is in the backend
// bundle but has no frontend nav route yet, so it is omitted here.)
export const SCOPED_MANAGER_PERMISSIONS: string[] = [
  Permission.MANAGE_CONNECTORS,
  Permission.MANAGE_DOCUMENT_SETS,
  Permission.MANAGE_AGENTS,
  Permission.ADD_AGENTS,
  Permission.MANAGE_USER_GROUPS,
  Permission.MANAGE_ACTIONS,
];

/**
 * The user's CAPABILITY set: raw effective permissions plus a group manager's
 * scoped tokens. This is `useUser().permissions`.
 *
 * How to gate UI (never rely on any of this for security — the backend enforces):
 *  - COARSE "can this user do X at all?" (nav links, page access, top-level
 *    "New X" buttons, scoped create/edit) → `hasPermission(permissions, X)`.
 *    A manager holds X, so this correctly returns true.
 *  - GLOBAL / org-wide action (feature an agent, publish org-wide, delete) →
 *    check the RAW `user.effective_permissions` (a manager's scoped tokens are
 *    NOT in there), or `isAdmin` when it is FULL_ADMIN-gated. Managers must not
 *    see these.
 *  - Action on a SPECIFIC item in a read-scoped list (e.g. edit an agent on the
 *    chat page) → use that item's backend editable flag, never a token check —
 *    a token can't say "…but only for this resource". (See the is_editable
 *    follow-up; until it lands these stay owner/admin-gated.)
 */
export function visibilityPermissions(
  user: User | null | undefined
): string[] {
  const base = user?.effective_permissions ?? [];
  if (!user?.is_group_manager) return base;
  return Array.from(new Set([...base, ...SCOPED_MANAGER_PERMISSIONS]));
}

// Derived from ADMIN_ROUTES — no hardcoded list to maintain.
// FULL_ADMIN_PANEL_ACCESS is the full-access override token, not a regular permission.
const ADMIN_ROUTE_PERMISSIONS: Set<string> = new Set(
  Object.values(ADMIN_ROUTES)
    .map((r) => r.requiredPermission)
    .filter((p) => p !== Permission.FULL_ADMIN_PANEL_ACCESS)
);

export function hasAnyAdminPermission(permissions: string[]): boolean {
  if (permissions.includes(Permission.FULL_ADMIN_PANEL_ACCESS)) return true;
  return permissions.some((p) => ADMIN_ROUTE_PERMISSIONS.has(p));
}

export function hasPermission(
  permissions: string[],
  ...required: string[]
): boolean {
  if (permissions.includes(Permission.FULL_ADMIN_PANEL_ACCESS)) return true;
  return required.some((r) => permissions.includes(r));
}

export function getFirstPermittedAdminRoute(permissions: string[]): string {
  for (const route of Object.values(ADMIN_ROUTES)) {
    if (!route.sidebarLabel) continue;
    if (
      permissions.includes(Permission.FULL_ADMIN_PANEL_ACCESS) ||
      permissions.includes(route.requiredPermission)
    ) {
      return route.path;
    }
  }
  // Fallback — should not be reached if hasAdminAccess is checked first
  return ADMIN_ROUTES.AGENTS.path;
}
