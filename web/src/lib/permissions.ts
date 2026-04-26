import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { Permission } from "@/lib/types";

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
