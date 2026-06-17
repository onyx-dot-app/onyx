import { redirect } from "next/navigation";
import type { Route } from "next";
import { requireAuth } from "@/lib/auth/requireAuth";
import { Permission } from "@/lib/types";
import { hasPermission } from "@/lib/permissions";

interface CraftManageLayoutProps {
  children: React.ReactNode;
}

// Server-side admin-only gate (the /api/admin/* endpoints exclude curators,
// unlike requireAdminAuth which allows them).
export default async function CraftManageLayout({
  children,
}: CraftManageLayoutProps) {
  const authResult = await requireAuth();
  if (authResult.redirect) {
    return redirect(authResult.redirect as Route);
  }
  if (
    !hasPermission(
      authResult.user?.effective_permissions ?? [],
      Permission.FULL_ADMIN_PANEL_ACCESS
    )
  ) {
    return redirect("/craft/v1" as Route);
  }
  return <>{children}</>;
}
