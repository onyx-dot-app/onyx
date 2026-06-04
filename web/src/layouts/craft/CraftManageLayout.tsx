import { redirect } from "next/navigation";
import type { Route } from "next";
import { requireAuth } from "@/lib/auth/requireAuth";
import { UserRole } from "@/lib/types";

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
  if (authResult.user?.role !== UserRole.ADMIN) {
    return redirect("/craft/v1" as Route);
  }
  return <>{children}</>;
}
