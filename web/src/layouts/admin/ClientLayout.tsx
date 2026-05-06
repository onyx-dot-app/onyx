"use client";

import AdminSidebar from "@/sections/sidebar/AdminSidebar";
import { usePathname } from "next/navigation";
import { useSettingsContext } from "@/providers/SettingsProvider";
import { ApplicationStatus } from "@/interfaces/settings";
import { Button, Text } from "@opal/components";
import { markdown } from "@opal/utils";
import useScreenSize from "@/hooks/useScreenSize";
import { SvgSidebar } from "@opal/icons";
import { useSidebarState } from "@/layouts/sidebar-layouts";

export interface ClientLayoutProps {
  children: React.ReactNode;
}

export default function ClientLayout({ children }: ClientLayoutProps) {
  const { setFolded } = useSidebarState();
  const { isMobile } = useScreenSize();
  const pathname = usePathname();
  const settings = useSettingsContext();

  // Certain admin panels have their own custom sidebar.
  // For those pages, we skip rendering the default `AdminSidebar` and let those individual pages render their own.
  const hasCustomSidebar = pathname.startsWith("/admin/connectors");

  return (
    <div className="h-screen w-screen flex overflow-hidden">
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

      {hasCustomSidebar ? (
        <div className="flex-1 min-w-0 min-h-0 overflow-y-auto">{children}</div>
      ) : (
        <>
          <AdminSidebar />
          <div
            data-main-container
            className="flex flex-1 flex-col min-w-0 min-h-0 overflow-y-auto"
          >
            {isMobile && (
              <div className="flex items-center px-4 pt-2">
                <Button
                  prominence="internal"
                  icon={SvgSidebar}
                  onClick={() => setFolded(false)}
                />
              </div>
            )}
            {children}
          </div>
        </>
      )}
    </div>
  );
}
