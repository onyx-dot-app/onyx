import { ADMIN_ROUTES } from "@/lib/admin-routes";

// Derived from ADMIN_ROUTES — no hardcoded list to maintain.
// "admin" is the full-access override token, not a regular permission.
const ADMIN_ROUTE_PERMISSIONS: Set<string> = new Set(
  Object.values(ADMIN_ROUTES)
    .map((r) => r.requiredPermission)
    .filter((p) => p !== "admin")
);

export function hasAnyAdminPermission(permissions: string[]): boolean {
  if (permissions.includes("admin")) return true;
  return permissions.some((p) => ADMIN_ROUTE_PERMISSIONS.has(p));
}

export function hasPermission(
  permissions: string[],
  ...required: string[]
): boolean {
  if (permissions.includes("admin")) return true;
  return required.some((r) => permissions.includes(r));
}

export function getFirstPermittedAdminRoute(permissions: string[]): string {
  for (const route of Object.values(ADMIN_ROUTES)) {
    if (!route.sidebarLabel) continue;
    if (
      permissions.includes("admin") ||
      permissions.includes(route.requiredPermission)
    ) {
      return route.path;
    }
  }
  // Fallback — should not be reached if hasAdminAccess is checked first
  return ADMIN_ROUTES.AGENTS.path;
}
