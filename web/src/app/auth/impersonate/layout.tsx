import { redirect } from "next/navigation";
import type { Route } from "next";
import { unstable_noStore as noStore } from "next/cache";
import { requireAuth } from "@/lib/auth/svcSS";

export interface LayoutProps {
  children: React.ReactNode;
}

// The auth gate must run server-side (as in app/layout.tsx): a client
// component that calls redirect() during render fires before the client-side
// user fetch resolves, so it redirects unconditionally — and prerender bakes
// it in as a route-level 307 on next >= 16.2.10.
export default async function Layout({ children }: LayoutProps) {
  noStore();

  const authResult = await requireAuth();
  if (authResult.redirect) {
    redirect(authResult.redirect as Route);
  }

  if (!authResult.user?.is_cloud_superuser) {
    redirect("/app" as Route);
  }

  return <>{children}</>;
}
