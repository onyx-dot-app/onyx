import { redirect } from "next/navigation";
import type { Route } from "next";
import { unstable_noStore as noStore } from "next/cache";
import { requireAuth } from "@/lib/auth/svcSS";
import { fetchSettingsSS } from "@/lib/settings/svcSS";
import CraftUpgradePage from "@/app/craft/components/CraftUpgradePage";

export interface LayoutProps {
  children: React.ReactNode;
}

/**
 * Build Layout - Minimal wrapper that handles authentication and feature flag check
 *
 * Child routes (/craft and /craft/v1) handle their own UI structure.
 * Shows the upgrade page when Craft is on but the tier is too low, and
 * redirects to /app if Onyx Craft is otherwise disabled.
 */
export default async function Layout({ children }: LayoutProps) {
  noStore();

  // Only check authentication - data fetching is done client-side
  const authResult = await requireAuth();

  if (authResult.redirect) {
    redirect(authResult.redirect as Route);
  }

  // Check if Onyx Craft is enabled via feature flag
  // Only explicit true enables the feature; false or undefined = disabled
  const settings = await fetchSettingsSS();
  if (settings?.settings?.onyx_craft_enabled !== true) {
    if (settings?.settings?.onyx_craft_requires_upgrade === true) {
      return <CraftUpgradePage />;
    }
    redirect("/app" as Route);
  }

  return <>{children}</>;
}
