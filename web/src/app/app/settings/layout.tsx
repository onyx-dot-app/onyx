"use client";

import { usePathname, useRouter } from "next/navigation";
import type { Route } from "next";
import { SettingsLayouts } from "@opal/layouts";
import { SidebarTab } from "@opal/components";
import { SvgSliders } from "@opal/icons";
import { InputSelect } from "@opal/components";
import { useUser } from "@/providers/UserProvider";
import { useIsMultiTenant } from "@/lib/auth/hooks";
import { Section } from "@/layouts/general-layouts";

interface LayoutProps {
  children: React.ReactNode;
}

interface SettingsTab {
  href: string;
  label: string;
}

export default function Layout({ children }: LayoutProps) {
  const pathname = usePathname();
  const router = useRouter();
  const { user } = useUser();
  const isMultiTenant = useIsMultiTenant();

  const showPasswordSection = Boolean(user?.password_configured);
  const showTokensSection = isMultiTenant !== null;
  const showAccountsAccessTab = showPasswordSection || showTokensSection;

  const tabs: SettingsTab[] = [
    { href: "/app/settings/general", label: "General" },
    { href: "/app/settings/chat-preferences", label: "Chat Preferences" },
    ...(showAccountsAccessTab
      ? [{ href: "/app/settings/accounts-access", label: "Accounts & Access" }]
      : []),
    { href: "/app/settings/connectors", label: "Connectors" },
  ];

  return (
    <SettingsLayouts.Root width="lg">
      <SettingsLayouts.Header icon={SvgSliders} title="Settings" divider />

      <SettingsLayouts.Body>
        <Section
          flexDirection="column"
          justifyContent="start"
          alignItems="stretch"
          gap={1.5}
          className="sm:flex-row sm:items-start"
        >
          {/* Narrow screens: dropdown navigation above the tab content */}
          <div
            data-testid="settings-tab-navigation-dropdown"
            className="sm:hidden"
          >
            <InputSelect
              value={pathname}
              onValueChange={(href) =>
                router.push(href as Route, { scroll: false })
              }
            >
              <InputSelect.Trigger placeholder="Select a section" />
              <InputSelect.Content>
                {tabs.map((tab) => (
                  <InputSelect.Item key={tab.href} value={tab.href}>
                    {tab.label}
                  </InputSelect.Item>
                ))}
              </InputSelect.Content>
            </InputSelect>
          </div>

          {/* Wide screens: left tab navigation */}
          <div
            data-testid="settings-left-tab-navigation"
            className="hidden sm:flex flex-col px-2 min-w-50"
          >
            {tabs.map((tab) => (
              <SidebarTab
                key={tab.href}
                href={tab.href}
                selected={pathname === tab.href}
              >
                {tab.label}
              </SidebarTab>
            ))}
          </div>

          {/* Tab Content */}
          {children}
        </Section>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
