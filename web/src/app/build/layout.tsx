import { redirect, notFound } from "next/navigation";
import type { Route } from "next";
import { unstable_noStore as noStore } from "next/cache";
import { requireAuth } from "@/lib/auth/requireAuth";
import { fetchSS } from "@/lib/utilsSS";

export interface LayoutProps {
  children: React.ReactNode;
}

/**
 * Check if Build Mode is enabled via PostHog feature flag.
 * Returns true if enabled, false otherwise.
 */
async function isBuildModeEnabled(): Promise<boolean> {
  try {
    const response = await fetchSS("/api/build-status/enabled");
    if (!response.ok) {
      // If the endpoint fails, default to disabled for safety
      return false;
    }
    const data = await response.json();
    return data.enabled === true;
  } catch {
    // If the fetch fails, default to disabled for safety
    return false;
  }
}

/**
 * Build Layout - Minimal wrapper that handles authentication and feature flag check
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

  // Check if Build Mode is enabled via PostHog feature flag
  const buildModeEnabled = await isBuildModeEnabled();
  if (!buildModeEnabled) {
    notFound();
  }

  return <>{children}</>;
}
