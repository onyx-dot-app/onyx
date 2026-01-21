"use client";

import AdminSidebar from "@/sections/sidebar/AdminSidebar";
import { usePathname } from "next/navigation";
import { useSettingsContext } from "@/components/settings/SettingsProvider";
import { ApplicationStatus } from "@/app/admin/settings/interfaces";
import Button from "@/refresh-components/buttons/Button";

export interface ClientLayoutProps {
  children: React.ReactNode;
  enableEnterprise: boolean;
  enableCloud: boolean;
}

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
          <div className="flex flex-1 flex-col min-w-0 min-h-0 overflow-y-auto py-10 px-4 md:px-12">
            {children}
          </div>
        </>
      )}
    </div>
  );
}
