"use client";

import AdminSidebar from "@/sections/sidebar/AdminSidebar";
import { User } from "@/lib/types";
import { usePathname } from "next/navigation";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import { useContext, useState } from "react";
import { UserSettingsModal } from "@/app/chat/components/modal/UserSettingsModal";
import { usePopup } from "@/components/admin/connectors/Popup";
import { useChatContext } from "@/refresh-components/contexts/ChatContext";
import { ApplicationStatus } from "@/app/admin/settings/interfaces";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { useFederatedOAuthStatus } from "@/lib/hooks/useFederatedOAuthStatus";

export interface ClientLayoutProps {
  user: User | null;
  children: React.ReactNode;
  enableEnterprise: boolean;
  enableCloud: boolean;
}

export function ClientLayout({
  user,
  children,
  enableEnterprise,
  enableCloud,
}: ClientLayoutProps) {
  const pathname = usePathname();
  const settings = useContext(SettingsContext);
  const [userSettingsOpen, setUserSettingsOpen] = useState(false);
  const toggleUserSettings = () => {
    setUserSettingsOpen(!userSettingsOpen);
  };
  const { llmProviders, ccPairs } = useChatContext();
  const { popup, setPopup } = usePopup();

  // Fetch federated-connector info so the modal can list/refresh them
  const {
    connectors: federatedConnectors,
    refetch: refetchFederatedConnectors,
  } = useFederatedOAuthStatus();

  if (
    (pathname && pathname.startsWith("/admin/connectors")) ||
    (pathname && pathname.startsWith("/admin/embeddings"))
  ) {
    return <>{children}</>;
  }

  return (
    <div className="h-screen w-screen flex overflow-y-hidden">
      {popup}

      {userSettingsOpen && (
        <UserSettingsModal
          llmProviders={llmProviders}
          setPopup={setPopup}
          onClose={() => setUserSettingsOpen(false)}
          defaultModel={user?.preferences?.default_model!}
          ccPairs={ccPairs}
          federatedConnectors={federatedConnectors}
          refetchFederatedConnectors={refetchFederatedConnectors}
        />
      )}

      {settings?.settings.application_status ===
        ApplicationStatus.PAYMENT_REMINDER && (
        <div className="fixed top-2 left-1/2 transform -translate-x-1/2 bg-amber-400 dark:bg-amber-500 text-gray-900 dark:text-gray-100 p-4 rounded-lg shadow-lg z-50 max-w-md text-center">
          <strong className="font-bold">Warning:</strong> Your trial ends in
          less than 5 days and no payment method has been added.
          <div className="mt-2">
            <Link href="/admin/billing">
              <Button
                variant="default"
                className="bg-amber-600 hover:bg-amber-700 text-white"
              >
                Update Billing Information
              </Button>
            </Link>
          </div>
        </div>
      )}

      <AdminSidebar
        enableCloudSS={enableCloud}
        enableEnterpriseSS={enableEnterprise}
      />
      <div className="overflow-y-scroll w-full">
        <div className="flex pt-10 pb-4 px-4 md:px-12">{children}</div>
      </div>
    </div>
  );
  // Is there a clean way to add this to some piece of text where we need to enbale for copy-paste in a react app?
}
