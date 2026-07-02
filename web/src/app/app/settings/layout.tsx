"use client";

import { usePathname, useRouter } from "next/navigation";
import type { Route } from "next";
import { SettingsLayouts } from "@opal/layouts";
import { SidebarTab, Text } from "@opal/components";
import { SvgSliders } from "@opal/icons";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { useUser } from "@/providers/UserProvider";
import { useAuthType } from "@/lib/hooks";
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
  const authType = useAuthType();

  const showPasswordSection = Boolean(user?.password_configured);
  const showTokensSection = authType !== null;
  const showAccountsAccessTab = showPasswordSection || showTokensSection;

  const tabs: SettingsTab[] = [
    { href: "/app/settings/general", label: "General" },
    { href: "/app/settings/chat-preferences", label: "Chat Preferences" },
    ...(showAccountsAccessTab
      ? [{ href: "/app/settings/accounts-access", label: "Accounts & Access" }]
      : []),
    { href: "/app/settings/connectors", label: "Connectors" },
  ];

  // Derive the trigger label from the pathname directly. InputSelect normally
  // surfaces the selected label via item registration, but its items are
  // unmounted while the dropdown is closed, so the label would otherwise be
  // missing on initial load.
  const activeTab = tabs.find((tab) => tab.href === pathname);

  return (
    <SettingsLayouts.Root width="lg">
      <SettingsLayouts.Header icon={SvgSliders} title="Settings" divider />

      <SettingsLayouts.Body>
        <Section
          flexDirection="column"
          justifyContent="start"
          alignItems="stretch"
          gap={1.5}
          className="md:flex-row md:items-start"
        >
          {/* Narrow screens: dropdown navigation above the tab content */}
          <div
            data-testid="settings-tab-navigation-dropdown"
            className="md:hidden"
          >
            <InputSelect
              value={pathname}
              onValueChange={(href) =>
                router.push(href as Route, { scroll: false })
              }
            >
              <InputSelect.Trigger placeholder="Select a section">
                {activeTab && (
                  <Text font="main-ui-body" color="text-04" nowrap>
                    {activeTab.label}
                  </Text>
                )}
              </InputSelect.Trigger>
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
            className="hidden md:flex flex-col px-2 min-w-50"
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
