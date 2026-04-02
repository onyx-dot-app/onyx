"use client";

import { usePathname } from "next/navigation";
import * as AppLayouts from "@/layouts/app-layouts";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { SidebarTab } from "@opal/components";
import { SvgSliders } from "@opal/icons";
import { useUser } from "@/providers/UserProvider";
import { useAuthType } from "@/lib/hooks";
import { Section } from "@/layouts/general-layouts";

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
          <Section
            flexDirection="row"
            justifyContent="start"
            alignItems="start"
            gap={1.5}
          >
            {/* Left: Tab Navigation */}
            <div
              data-testid="settings-left-tab-navigation"
              className="flex flex-col px-2 min-w-[12.5rem]"
            >
              <SidebarTab
                href="/app/settings/general"
                state={
                  pathname === "/app/settings/general" ? "selected" : "empty"
                }
              >
                General
              </SidebarTab>
              <SidebarTab
                href="/app/settings/chat-preferences"
                state={
                  pathname === "/app/settings/chat-preferences"
                    ? "selected"
                    : "empty"
                }
              >
                Chat Preferences
              </SidebarTab>
              {showAccountsAccessTab && (
                <SidebarTab
                  href="/app/settings/accounts-access"
                  state={
                    pathname === "/app/settings/accounts-access"
                      ? "selected"
                      : "empty"
                  }
                >
                  Accounts & Access
                </SidebarTab>
              )}
              <SidebarTab
                href="/app/settings/connectors"
                state={
                  pathname === "/app/settings/connectors" ? "selected" : "empty"
                }
              >
                Connectors
              </SidebarTab>
            </div>

            {/* Right: Tab Content */}
            {children}
          </Section>
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    </AppLayouts.Root>
  );
}
