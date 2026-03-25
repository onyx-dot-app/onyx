"use client";

import AdminSidebar from "@/sections/sidebar/AdminSidebar";
import { usePathname } from "next/navigation";
import { useSettingsContext } from "@/providers/SettingsProvider";
import { ApplicationStatus } from "@/interfaces/settings";
import { Button } from "@opal/components";
import { cn } from "@/lib/utils";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

export interface ClientLayoutProps {
  children: React.ReactNode;
  enableCloud: boolean;
}

// TODO (@raunakab): Migrate ALL admin pages to use SettingsLayouts from
// `@/layouts/settings-layouts`. Once every page manages its own layout,
// the `py-10 px-4 md:px-12` padding below can be removed entirely and
// this prefix list can be deleted.
const SETTINGS_LAYOUT_PREFIXES = [
  ADMIN_ROUTES.CHAT_PREFERENCES.path,
  ADMIN_ROUTES.IMAGE_GENERATION.path,
  ADMIN_ROUTES.VOICE.path,
  ADMIN_ROUTES.WEB_SEARCH.path,
  ADMIN_ROUTES.MCP_ACTIONS.path,
  ADMIN_ROUTES.OPENAPI_ACTIONS.path,
  ADMIN_ROUTES.BILLING.path,
  ADMIN_ROUTES.INDEX_MIGRATION.path,
  ADMIN_ROUTES.DISCORD_BOTS.path,
  ADMIN_ROUTES.THEME.path,
  ADMIN_ROUTES.LLM_MODELS.path,
  ADMIN_ROUTES.AGENTS.path,
  ADMIN_ROUTES.USERS.path,
  ADMIN_ROUTES.TOKEN_RATE_LIMITS.path,
  ADMIN_ROUTES.INDEX_SETTINGS.path,
  ADMIN_ROUTES.DOCUMENT_PROCESSING.path,
  ADMIN_ROUTES.CODE_INTERPRETER.path,
  ADMIN_ROUTES.API_KEYS.path,
  ADMIN_ROUTES.ADD_CONNECTOR.path,
  ADMIN_ROUTES.INDEXING_STATUS.path,
  ADMIN_ROUTES.DOCUMENTS.path,
  ADMIN_ROUTES.DEBUG.path,
  ADMIN_ROUTES.KNOWLEDGE_GRAPH.path,
  ADMIN_ROUTES.SLACK_BOTS.path,
  ADMIN_ROUTES.STANDARD_ANSWERS.path,
  ADMIN_ROUTES.GROUPS.path,
  ADMIN_ROUTES.PERFORMANCE.path,
  ADMIN_ROUTES.SCIM.path,
  ADMIN_ROUTES.VOICE.path,
];

export function ClientLayout({ children, enableCloud }: ClientLayoutProps) {
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
            <Button width="full" href="/admin/billing">
              Update Billing Information
            </Button>
          </div>
        </div>
      )}

      {hasCustomSidebar ? (
        <div className="flex-1 min-w-0 min-h-0 overflow-y-auto">{children}</div>
      ) : (
        <>
          <AdminSidebar enableCloudSS={enableCloud} />
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
