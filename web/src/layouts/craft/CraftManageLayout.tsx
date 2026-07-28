import { redirect } from "next/navigation";
import type { Route } from "next";
import { requireAuth } from "@/lib/auth/requireAuth";
import { Permission } from "@/lib/types";
import { hasPermission } from "@/lib/permissions";

interface CraftManageLayoutProps {
  children: React.ReactNode;
}

// admin_capabilities + MANAGE_SKILLS (not effective_permissions) so a scoped skills
// manager — whose admin routes are allow_scope=True — reaches the page, not just admins.
export default async function CraftManageLayout({
  children,
}: CraftManageLayoutProps) {
  const authResult = await requireAuth();
  if (authResult.redirect) {
    return redirect(authResult.redirect as Route);
  }
  if (
    !hasPermission(
      authResult.user?.admin_capabilities ?? [],
      Permission.MANAGE_SKILLS
    )
  ) {
    return redirect("/craft/v1" as Route);
  }
  return <>{children}</>;
}
