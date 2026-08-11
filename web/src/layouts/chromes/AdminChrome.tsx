"use client";

import { createContext, useContext, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import AdminSidebar from "@/sections/sidebar/AdminSidebar";
import { usePathname } from "next/navigation";
import { useSettings } from "@/lib/settings/hooks";
import { useAdminDocumentTitle } from "@/lib/app/hooks";
import { ApplicationStatus } from "@/lib/settings/types";
import { Button, Text } from "@opal/components";
import { markdown } from "@opal/utils";
import useScreenSize from "@/hooks/useScreenSize";
import { SvgSidebar, SvgSimpleLoader } from "@opal/icons";
import { RootLayout, useSidebarState } from "@opal/layouts";
import { Section } from "@/layouts/general-layouts";
import { isVectorDbRequiredRoute } from "@/lib/admin-routes";
import LiteModeIndexingNotice from "@/sections/admin/LiteModeIndexingNotice";

export interface AdminChromeProps {
  children: React.ReactNode;
}

// The create-connector page (`/admin/connectors/<connector>`) renders its own
// sidebar. Routes below it do not.
const CUSTOM_SIDEBAR_ROUTE = /^\/admin\/connectors\/[^/]+\/?$/;

// Lets a page render its own sidebar into the chrome as a sibling of the main
// content column — i.e. *outside* the scrollable region — so it stays pinned
// while the page scrolls. The page keeps ownership (and React context) of the
// sidebar; only the DOM is portaled up next to `RootLayout.App`.
const AdminCustomSidebarSlotContext = createContext<HTMLElement | null>(null);

export function AdminCustomSidebarPortal({
  children,
}: {
  children: ReactNode;
}) {
  const slot = useContext(AdminCustomSidebarSlotContext);
  if (!slot) return null;
  return createPortal(children, slot);
}

export default function AdminChrome({ children }: AdminChromeProps) {
  const { setFolded } = useSidebarState();
  const { isMobile } = useScreenSize();
  const pathname = usePathname();
  const { vectorDbEnabled, isLoading, application_status } = useSettings();
  useAdminDocumentTitle();

  const [customSidebarSlot, setCustomSidebarSlot] =
    useState<HTMLDivElement | null>(null);

  // Certain admin panels have their own custom sidebar.
  // For those pages, we skip rendering the default `AdminSidebar` and let those individual pages render their own.
  // The OAuth callback / finalize interstitials below the create-connector page
  // render no sidebar of their own, so they keep the default one.
  const hasCustomSidebar = CUSTOM_SIDEBAR_ROUTE.test(pathname);

  let content = children;
  if (isVectorDbRequiredRoute(pathname)) {
    if (isLoading) {
      content = (
        <Section padding={8}>
          <SvgSimpleLoader className="h-6 w-6" />
        </Section>
      );
    } else if (!vectorDbEnabled) {
      content = <LiteModeIndexingNotice />;
    }
  }

  return (
    <AdminCustomSidebarSlotContext.Provider value={customSidebarSlot}>
      <RootLayout.Root>
        {application_status === ApplicationStatus.PAYMENT_REMINDER && (
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

        {hasCustomSidebar ? (
          // `display: contents` so the portaled sidebar column becomes the
          // direct flex child of `RootLayout.Root`, exactly like `AdminSidebar`.
          <div ref={setCustomSidebarSlot} className="contents" />
        ) : (
          <AdminSidebar />
        )}

        <RootLayout.App data-main-container>
          {/* On mobile every sidebar is an off-screen overlay, so the main
              column always needs a control to bring it back. */}
          {isMobile && (
            <RootLayout.Header>
              <div className="h-full flex items-center px-4 py-2">
                <Button
                  prominence="internal"
                  icon={SvgSidebar}
                  aria-label="Open Sidebar"
                  onClick={() => setFolded(false)}
                />
              </div>
            </RootLayout.Header>
          )}
          <RootLayout.MainContent>{content}</RootLayout.MainContent>
        </RootLayout.App>
      </RootLayout.Root>
    </AdminCustomSidebarSlotContext.Provider>
  );
}
