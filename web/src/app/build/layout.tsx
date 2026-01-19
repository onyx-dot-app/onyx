import { redirect } from "next/navigation";
import type { Route } from "next";
import { unstable_noStore as noStore } from "next/cache";
import { requireAuth } from "@/lib/auth/requireAuth";

export interface LayoutProps {
  children: React.ReactNode;
}

/**
 * Build Layout - Minimal wrapper that handles authentication
 *
 * Child routes (/build and /build/v1) handle their own UI structure.
 */
export default async function Layout({ children }: LayoutProps) {
  noStore();

  // Only check authentication - data fetching is done client-side
  const authResult = await requireAuth();

  if (authResult.redirect) {
    redirect(authResult.redirect as Route);
  }

  return <>{children}</>;
}
