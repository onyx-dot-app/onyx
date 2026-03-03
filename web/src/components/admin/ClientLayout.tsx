"use client";

import AdminSidebar from "@/sections/sidebar/AdminSidebar";
import { usePathname } from "next/navigation";
import { useSettingsContext } from "@/providers/SettingsProvider";
import { ApplicationStatus } from "@/interfaces/settings";
import Button from "@/refresh-components/buttons/Button";
import { cn } from "@/lib/utils";
import { ADMIN_PATHS } from "@/lib/admin-routes";

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
  ADMIN_PATHS.CHAT_PREFERENCES,
  ADMIN_PATHS.IMAGE_GENERATION,
  ADMIN_PATHS.WEB_SEARCH,
  ADMIN_PATHS.MCP_ACTIONS,
  ADMIN_PATHS.OPENAPI_ACTIONS,
  ADMIN_PATHS.BILLING,
  ADMIN_PATHS.INDEX_MIGRATION,
  ADMIN_PATHS.DISCORD_BOTS,
  ADMIN_PATHS.THEME,
  ADMIN_PATHS.LLM_MODELS,
  ADMIN_PATHS.AGENTS,
  ADMIN_PATHS.USERS,
  ADMIN_PATHS.TOKEN_RATE_LIMITS,
  ADMIN_PATHS.SEARCH_SETTINGS,
  ADMIN_PATHS.DOCUMENT_PROCESSING,
  ADMIN_PATHS.CODE_INTERPRETER,
  ADMIN_PATHS.API_KEYS,
  ADMIN_PATHS.ADD_CONNECTOR,
  ADMIN_PATHS.INDEXING_STATUS,
  ADMIN_PATHS.DOCUMENTS,
  ADMIN_PATHS.DEBUG,
  ADMIN_PATHS.KNOWLEDGE_GRAPH,
  ADMIN_PATHS.SLACK_BOTS,
  ADMIN_PATHS.STANDARD_ANSWERS,
  ADMIN_PATHS.GROUPS,
  ADMIN_PATHS.PERFORMANCE,
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
