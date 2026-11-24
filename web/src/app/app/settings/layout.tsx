"use client";

import { useNavigation, usePathname } from "@opal/navigation";
import type { Route } from "next";
import { useTranslations } from "next-intl";
import { SettingsLayouts, Section } from "@opal/layouts";
import { InputSingleSelect, SidebarTab } from "@opal/components";
import { SvgSliders } from "@opal/icons";
import useSWR from "swr";
import { useUser } from "@/providers/UserProvider";
import { useSettings } from "@/lib/settings/hooks";
import { useTierAtLeast } from "@/lib/tiers/hooks";
import { LLM_GATEWAY_MIN_TIER } from "@/lib/tiers/utils";
import { useLanguageModels } from "@/lib/languageModels/hooks";
import { hasVisibleLLMModel } from "@/lib/languageModels/utils";
import { hasPermission } from "@/lib/permissions/utils";
import { Permission } from "@/lib/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";
import useFederatedOAuthStatus from "@/hooks/useFederatedOAuthStatus";
import type { PAT } from "@/views/settings/types";

interface LayoutProps {
  children: React.ReactNode;
}

interface SettingsTab {
  href: Route;
  label: string;
}

export default function Layout({ children }: LayoutProps) {
  const t = useTranslations("settings.layout");
  const pathname = usePathname();
  const navigation = useNavigation();
  const { permissions } = useUser();
  const { oauth_provider_enabled } = useSettings();
  const gatewayTier = useTierAtLeast(LLM_GATEWAY_MIN_TIER);
  const { llmProviders } = useLanguageModels();
  const { connectors: federatedConnectors } = useFederatedOAuthStatus();
  const canCreatePAT = hasPermission(
    permissions,
    Permission.CREATE_USER_API_KEYS
  );
  // Users who cannot create tokens still need the tab to manage the ones
  // they own.
  const { data: pats } = useSWR<PAT[]>(
    canCreatePAT ? null : SWR_KEYS.userPats,
    errorHandlingFetcher
  );

  // The 3rd Party Access tab shows when any of its sections has something to show.
  const showThirdPartyAccessTab =
    canCreatePAT ||
    (pats?.length ?? 0) > 0 ||
    Boolean(oauth_provider_enabled) ||
    federatedConnectors.length > 0 ||
    (gatewayTier && hasVisibleLLMModel(llmProviders));

  const tabs: SettingsTab[] = [
    { href: "/app/settings/account", label: t("tabs.account.label") },
    { href: "/app/settings/appearance", label: t("tabs.appearance.label") },
    {
      href: "/app/settings/chat-preferences",
      label: t("tabs.chatPreferences.label"),
    },
    ...(showThirdPartyAccessTab
      ? ([
          {
            href: "/app/settings/third-party-access",
            label: t("tabs.thirdPartyAccess.label"),
          },
        ] satisfies SettingsTab[])
      : []),
    { href: "/app/settings/usage", label: t("tabs.usage.label") },
  ];

  // A route outside `tabs` selects nothing, so the select shows its
  // placeholder instead of the raw path.
  const activeTab = tabs.find((tab) => tab.href === pathname);

  return (
    <SettingsLayouts.Root width="lg">
      <SettingsLayouts.Header
        icon={SvgSliders}
        title={t("header.title")}
        divider
      />

      <SettingsLayouts.Body>
        <Section
          flexDirection="column"
          justifyContent="start"
          alignItems="stretch"
          gap={6}
          className="sm:flex-row sm:items-start"
        >
          {/* Narrow screens: dropdown navigation above the tab content */}
          <div
            data-testid="settings-tab-navigation-dropdown"
            className="sm:hidden"
          >
            <InputSingleSelect
              // A route outside `tabs` shows the placeholder, not the raw path.
              value={activeTab?.href ?? ""}
              onValueChange={(href) =>
                // SAFETY: the options are the static hrefs in `tabs`.
                navigation.go(href as Route, { scroll: false })
              }
              placeholder={t("sectionSelect.placeholder")}
              options={tabs.map((tab) => ({
                value: tab.href,
                title: tab.label,
              }))}
            />
          </div>

          {/* Wide screens: left tab navigation */}
          <div
            data-testid="settings-left-tab-navigation"
            className="hidden sm:flex flex-col px-2 min-w-50"
          >
            {tabs.map((tab) => (
              <SidebarTab
                key={tab.href}
                {...navigation.linkTo(tab.href, { scroll: false })}
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
