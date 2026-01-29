"use client";

import { usePathname } from "next/navigation";
import * as AppLayouts from "@/layouts/app-layouts";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import SidebarTab from "@/refresh-components/buttons/SidebarTab";
import { SvgSliders } from "@opal/icons";
import { useUser } from "@/components/user/UserProvider";
import { useAuthType } from "@/lib/hooks";
import { AuthType } from "@/lib/constants";

interface LayoutProps {
  children: React.ReactNode;
}

export default function Layout({ children }: LayoutProps) {
  const pathname = usePathname();
  const { user } = useUser();
  const authType = useAuthType();

  const showPasswordSection = Boolean(user?.password_configured);
  const showTokensSection = authType !== null;
  const showAccountsAccessTab = showPasswordSection || showTokensSection;

  return (
    <AppLayouts.Root>
      <SettingsLayouts.Root width="lg">
        <SettingsLayouts.Header icon={SvgSliders} title="Settings" separator />

        <SettingsLayouts.Body>
          <div className="grid grid-cols-[auto_1fr]">
            {/* Left: Tab Navigation */}
            <div className="flex flex-col px-2 w-[12.5rem]">
              <SidebarTab
                href="/app/settings/general"
                transient={pathname === "/app/settings/general"}
              >
                General
              </SidebarTab>
              <SidebarTab
                href="/app/settings/chat-preferences"
                transient={pathname === "/app/settings/chat-preferences"}
              >
                Chat Preferences
              </SidebarTab>
              {showAccountsAccessTab && (
                <SidebarTab
                  href="/app/settings/accounts-access"
                  transient={pathname === "/app/settings/accounts-access"}
                >
                  Accounts & Access
                </SidebarTab>
              )}
              <SidebarTab
                href="/app/settings/connectors"
                transient={pathname === "/app/settings/connectors"}
              >
                Connectors
              </SidebarTab>
            </div>

            {/* Right: Tab Content */}
            <div className="px-4">{children}</div>
          </div>
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    </AppLayouts.Root>
  );
}
