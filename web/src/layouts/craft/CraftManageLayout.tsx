import { redirect } from "next/navigation";
import type { Route } from "next";
import { requireAuth } from "@/lib/auth/svcSS";
import { Permission } from "@/lib/types";
import { hasPermission } from "@/lib/permissions";

interface CraftManageLayoutProps {
  children: React.ReactNode;
}

// Two routes share this factory but need different gates: /skills/manage passes
// MANAGE_SKILLS (lets scoped managers in), /apps/manage passes FULL_ADMIN_PANEL_ACCESS
// (its /admin/apps endpoints are admin-only). Both read admin_capabilities, which adds
// the scoped-manager perms but never the full-admin token — so the apps gate still
// rejects scoped managers.
export function createCraftManageLayout(required: Permission) {
  return async function CraftManageLayout({
    children,
  }: CraftManageLayoutProps) {
    const authResult = await requireAuth();
    if (authResult.redirect) {
      return redirect(authResult.redirect as Route);
    }
    if (!hasPermission(authResult.user?.admin_capabilities ?? [], required)) {
      return redirect("/craft/v1" as Route);
    }
    return <>{children}</>;
  };
}
