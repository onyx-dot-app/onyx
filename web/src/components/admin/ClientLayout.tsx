"use client";

import AdminSidebar from "@/sections/sidebar/AdminSidebar";
import { usePathname } from "next/navigation";
import { useSettingsContext } from "@/providers/SettingsProvider";
import { ApplicationStatus } from "@/interfaces/settings";
import Button from "@/refresh-components/buttons/Button";
import { cn } from "@/lib/utils";

export interface ClientLayoutProps {
  children: React.ReactNode;
  enableEnterprise: boolean;
  enableCloud: boolean;
}

// TODO (@raunakab): Migrate ALL admin pages to use SettingsLayouts from
// `@/layouts/settings-layouts`. Once every page manages its own layout,
// the `py-10 px-4 md:px-12` padding below can be removed entirely and
// this prefix list can be deleted.
const SETTINGS_LAYOUT_PREFIXES = [
  "/admin/configuration/chat-preferences",
  "/admin/configuration/image-generation",
  "/admin/configuration/web-search",
  "/admin/actions/mcp",
  "/admin/actions/open-api",
  "/admin/billing",
  "/admin/document-index-migration",
  "/admin/discord-bot",
  "/admin/theme",
];

export function ClientLayout({
  children,
  enableEnterprise,
  enableCloud,
}: ClientLayoutProps) {
  const pathname = usePathname();
  const settings = useSettingsContext();

  // Certain admin panels have their own custom sidebar.
  // For those pages, we skip rendering the default `AdminSidebar` and let those individual pages render their own.
  const hasCustomSidebar =
    pathname.startsWith("/admin/connectors") ||
    pathname.startsWith("/admin/embeddings");

  // Pages using SettingsLayouts handle their own padding/centering.
  const hasOwnLayout = SETTINGS_LAYOUT_PREFIXES.some((prefix) =>
    pathname.startsWith(prefix)
  );

  return (
    <div className="h-screen w-screen flex overflow-hidden">
      {settings.settings.application_status ===
        ApplicationStatus.PAYMENT_REMINDER && (
        <div className="fixed top-2 left-1/2 transform -translate-x-1/2 bg-amber-400 dark:bg-amber-500 text-gray-900 dark:text-gray-100 p-4 rounded-lg shadow-lg z-50 max-w-md text-center">
          <strong className="font-bold">Warning:</strong> Your trial ends in
          less than 5 days and no payment method has been added.
          <div className="mt-2">
            <Button className="w-full" href="/admin/billing">
              Update Billing Information
            </Button>
          </div>
        </div>
      )}

      {hasCustomSidebar ? (
        <div className="flex-1 min-w-0 min-h-0 overflow-y-auto">{children}</div>
      ) : (
        <>
          <AdminSidebar
            enableCloudSS={enableCloud}
            enableEnterpriseSS={enableEnterprise}
          />
          <div
            data-main-container
            className={cn(
              "flex flex-1 flex-col min-w-0 min-h-0 overflow-y-auto",
              !hasOwnLayout && "py-10 px-4 md:px-12"
            )}
          >
            {children}
          </div>
        </>
      )}
    </div>
  );
}
