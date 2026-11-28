"use client";

import type { Route } from "next";
import { useTranslations } from "next-intl";
import useSWR from "swr";
import { SidebarTab } from "@opal/components";
import { SidebarLayouts } from "@opal/layouts";
import { useNavigation, usePathname } from "@opal/navigation";
import {
  SvgBarChart,
  SvgBubbleText,
  SvgKey,
  SvgSun,
  SvgUser,
} from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import { useUser } from "@/providers/UserProvider";
import { useSettings } from "@/lib/settings/hooks";
import { useTierAtLeast } from "@/lib/tiers/hooks";
import { LLM_GATEWAY_MIN_TIER } from "@/lib/tiers/utils";
import { useLanguageModels } from "@/lib/languageModels/hooks";
import { hasVisibleLLMModel } from "@/lib/languageModels/utils";
import { usePlaygroundRestriction } from "@/lib/playground/hooks";
import { PlaygroundRestrictedFeature } from "@/lib/playground/types";
import { hasPermission } from "@/lib/permissions/utils";
import { Permission } from "@/lib/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";
import useFederatedOAuthStatus from "@/hooks/useFederatedOAuthStatus";
import type { PAT } from "@/views/settings/types";

interface SettingsTab {
  href: Route;
  label: string;
  icon: IconFunctionComponent;
}

/** The Settings window: one tab per user settings page. */
export default function SettingsSidebarContent() {
  const t = useTranslations("settings.layout");
  const pathname = usePathname();
  const navigation = useNavigation();
  const { permissions } = useUser();
  const { oauth_provider_enabled } = useSettings();
  const gatewayTier = useTierAtLeast(LLM_GATEWAY_MIN_TIER);
  const { llmProviders } = useLanguageModels();
  const gatewayRestriction = usePlaygroundRestriction(
    PlaygroundRestrictedFeature.LLM_GATEWAY
  );
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
  // On the playground the gateway section shows the playground notice, so the
  // tab shows whatever the tier and the model list say.
  const showThirdPartyAccessTab =
    canCreatePAT ||
    (pats?.length ?? 0) > 0 ||
    Boolean(oauth_provider_enabled) ||
    federatedConnectors.length > 0 ||
    gatewayRestriction.restricted ||
    (gatewayTier && hasVisibleLLMModel(llmProviders));

  const tabs: SettingsTab[] = [
    {
      href: "/app/settings/account",
      label: t("tabs.account.label"),
      icon: SvgUser,
    },
    {
      href: "/app/settings/appearance",
      label: t("tabs.appearance.label"),
      icon: SvgSun,
    },
    {
      href: "/app/settings/chat-preferences",
      label: t("tabs.chatPreferences.label"),
      icon: SvgBubbleText,
    },
    ...(showThirdPartyAccessTab
      ? ([
          {
            href: "/app/settings/third-party-access",
            label: t("tabs.thirdPartyAccess.label"),
            icon: SvgKey,
          },
        ] satisfies SettingsTab[])
      : []),
    {
      href: "/app/settings/usage",
      label: t("tabs.usage.label"),
      icon: SvgBarChart,
    },
  ];

  return (
    <SidebarLayouts.Body scrollKey="settings-sidebar">
      <SidebarLayouts.Section>
        <div data-testid="settings-left-tab-navigation">
          {tabs.map((tab) => (
            <SidebarTab
              key={tab.href}
              icon={tab.icon}
              {...navigation.linkTo(tab.href, { scroll: false })}
              selected={pathname === tab.href}
            >
              {tab.label}
            </SidebarTab>
          ))}
        </div>
      </SidebarLayouts.Section>
    </SidebarLayouts.Body>
  );
}
