"use client";

import AdminSidebar from "@/sections/sidebar/AdminSidebar";
import { usePathname, useRouter } from "next/navigation";
import type { Route } from "next";
import { useEffect } from "react";
import { useSettingsContext } from "@/providers/SettingsProvider";
import { useUser } from "@/providers/UserProvider";
import { ApplicationStatus } from "@/interfaces/settings";
import { Button, Text } from "@opal/components";
import { markdown } from "@opal/utils";
import useScreenSize from "@/hooks/useScreenSize";
import { SvgSidebar, SvgSimpleLoader } from "@opal/icons";
import { RootLayout, useSidebarState } from "@opal/layouts";
import { Section } from "@/layouts/general-layouts";
import { isVectorDbRequiredRoute, matchAdminRoute } from "@/lib/admin-routes";
import { getFirstPermittedAdminRoute, hasPermission } from "@/lib/permissions";
import LiteModeIndexingNotice from "@/sections/admin/LiteModeIndexingNotice";

export interface AdminChromeProps {
  children: React.ReactNode;
}

export default function AdminChrome({ children }: AdminChromeProps) {
  const { setFolded } = useSidebarState();
  const { isMobile } = useScreenSize();
  const pathname = usePathname();
  const settings = useSettingsContext();
  const router = useRouter();
  const { adminCapabilities } = useUser();

  // Match-only per-page gate: if this page is a known admin route the user lacks the
  // permission for (a group manager landing on a full-admin page), send them to their
  // first permitted admin page. Unlisted detail sub-pages are left to the backend gate.
  const matched = matchAdminRoute(pathname);
  const denied =
    matched !== undefined &&
    !hasPermission(adminCapabilities, matched.requiredPermission);

  useEffect(() => {
    if (denied) {
      router.replace(getFirstPermittedAdminRoute(adminCapabilities) as Route);
    }
  }, [denied, router, adminCapabilities]);

  // Certain admin panels have their own custom sidebar.
  // For those pages, we skip rendering the default `AdminSidebar` and let those individual pages render their own.
  const hasCustomSidebar = pathname.startsWith("/admin/connectors");

  // Lite mode (no vector DB): connector/indexing pages can't run, show a notice.
  const vectorDbEnabled = settings.settings.vector_db_enabled !== false;
  let content = children;
  if (isVectorDbRequiredRoute(pathname)) {
    if (settings.settingsLoading) {
      content = (
        <Section padding={2}>
          <SvgSimpleLoader className="h-6 w-6" />
        </Section>
      );
    } else if (!vectorDbEnabled) {
      content = <LiteModeIndexingNotice />;
    }
  }

  if (denied) return null;

  return (
    <RootLayout.Root>
      {settings.settings.application_status ===
        ApplicationStatus.PAYMENT_REMINDER && (
        <div className="fixed top-2 left-1/2 -translate-x-1/2 bg-status-warning-01 p-4 rounded-lg shadow-lg z-50 max-w-md text-center">
          <Text font="main-ui-body" color="text-05">
            {markdown(
              "**Warning:** Your trial ends in less than 5 days and no payment method has been added."
            )}
          </Text>
          <div className="mt-2">
            <Button width="full" href="/admin/billing">
              Update Billing Information
            </Button>
          </div>
        </div>
      )}

      {!hasCustomSidebar && <AdminSidebar />}

      <RootLayout.App data-main-container>
        {isMobile && !hasCustomSidebar && (
          <RootLayout.Header>
            <div className="h-full flex items-center px-4 py-2">
              <Button
                prominence="internal"
                icon={SvgSidebar}
                onClick={() => setFolded(false)}
              />
            </div>
          </RootLayout.Header>
        )}
        <RootLayout.MainContent>{content}</RootLayout.MainContent>
      </RootLayout.App>
    </RootLayout.Root>
  );
}
