import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { Permission, User } from "@/lib/types";

// Tokens a group manager may exercise, scoped to the groups they manage — mirrors
// the backend SCOPED_MANAGER_PERMISSIONS bundle. Surfaced to the client for NAV
// VISIBILITY ONLY; real enforcement is backend GATE 2. (MANAGE_SKILLS is in the
// backend bundle but has no frontend nav route yet, so it is omitted here.)
export const SCOPED_MANAGER_PERMISSIONS: string[] = [
  Permission.MANAGE_CONNECTORS,
  Permission.MANAGE_DOCUMENT_SETS,
  Permission.MANAGE_AGENTS,
  Permission.ADD_AGENTS,
  Permission.MANAGE_USER_GROUPS,
  Permission.MANAGE_ACTIONS,
];

// Effective permissions for nav/visibility. A group manager is treated as holding
// the scoped manage tokens so the sidebar reveals their scoped admin pages. NOT a
// security boundary — the backend enforces scope on every request.
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
