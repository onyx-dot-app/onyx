"use client";

import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { useSettings } from "@/lib/settings/hooks";
import { SidebarLayouts, useSidebarState } from "@opal/layouts";
import { useCustomAnalyticsEnabled } from "@/lib/hooks/useCustomAnalyticsEnabled";
import { useUser } from "@/providers/UserProvider";
import { Divider, InputTypeIn, SidebarTab } from "@opal/components";
import { SvgSearch, SvgX } from "@opal/icons";
import {
  useBillingInformation,
  useLicense,
  hasActiveSubscription,
} from "@/lib/billing";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { Tier } from "@/lib/settings/types";
import useFilter from "@/hooks/useFilter";
import AccountPopover from "@/sections/sidebar/AccountPopover";
import { markdown } from "@opal/utils";
import {
  buildItems,
  groupBySection,
  type AdminNavItemId,
  type AdminNavSectionId,
  type FeatureFlags,
  type SidebarItemEntry,
} from "@/lib/admin-sidebar-utils";
import { renderSidebarLogo } from "@/lib/sidebar/utils";
import { useShowLogoWhenFolded } from "@/lib/sidebar/hooks";

export default function AdminSidebar() {
  const t = useTranslations("sidebar");
  const { folded, setFolded } = useSidebarState();
  const showLogoWhenFolded = useShowLogoWhenFolded();
  const searchRef = useRef<HTMLInputElement>(null);
  const [focusSearch, setFocusSearch] = useState(false);

  useEffect(() => {
    if (focusSearch && !folded && searchRef.current) {
      searchRef.current.focus();
      setFocusSearch(false);
    }
  }, [focusSearch, folded]);
  const pathname = usePathname();
  const { customAnalyticsEnabled } = useCustomAnalyticsEnabled();
  const { adminCapabilities } = useUser();
  const settings = useSettings();
  const tier = settings?.tier;
  const { data: billingData, isLoading: billingLoading } =
    useBillingInformation();
  const { data: licenseData, isLoading: licenseLoading } = useLicense();
  // Default to true while loading to avoid flashing "Upgrade Plan"
  const hasSubscriptionOrLicense =
    billingLoading || licenseLoading
      ? true
      : Boolean(
          (billingData && hasActiveSubscription(billingData)) ||
          licenseData?.has_license
        );

  // Tier is not folded in here: ENTERPRISE is declared as the route's `requiredTier`, so
  // a lower tier renders the entry disabled with an upsell rather than hiding it.
  const flags: FeatureFlags = {
    vectorDbEnabled: settings?.vectorDbEnabled !== false,
    enableCloud: NEXT_PUBLIC_CLOUD_ENABLED,
    tier,
    customAnalyticsEnabled,
    hasSubscription: hasSubscriptionOrLicense,
    hooksEnabled: settings?.hooks_enabled ?? false,
    opensearchEnabled: settings?.opensearch_indexing_enabled ?? false,
    queryHistoryEnabled:
      settings?.query_history_type !== "disabled" &&
      !settings?.hide_query_history_from_admin_panel,
    craftAvailable: settings?.onyx_craft_available ?? false,
  };

  const allItems = buildItems(adminCapabilities, flags, settings);

  // Built with literal keys so the message ids stay statically checkable.
  const navLabels = useMemo<Record<AdminNavItemId, string>>(
    () => ({
      languageModels: t("adminNav.items.languageModels.label"),
      webSearch: t("adminNav.items.webSearch.label"),
      imageGeneration: t("adminNav.items.imageGeneration.label"),
      voice: t("adminNav.items.voice.label"),
      codeInterpreter: t("adminNav.items.codeInterpreter.label"),
      chatPreferences: t("adminNav.items.chatPreferences.label"),
      craftAccess: t("adminNav.items.craftAccess.label"),
      craftApps: t("adminNav.items.craftApps.label"),
      craftPreferences: t("adminNav.items.craftPreferences.label"),
      customAnalytics: t("adminNav.items.customAnalytics.label"),
      agents: t("adminNav.items.agents.label"),
      mcpActions: t("adminNav.items.mcpActions.label"),
      openapiActions: t("adminNav.items.openapiActions.label"),
      existingConnectors: t("adminNav.items.existingConnectors.label"),
      addConnector: t("adminNav.items.addConnector.label"),
      documentSets: t("adminNav.items.documentSets.label"),
      indexSettings: t("adminNav.items.indexSettings.label"),
      serviceAccounts: t("adminNav.items.serviceAccounts.label"),
      slackIntegration: t("adminNav.items.slackIntegration.label"),
      discordIntegration: t("adminNav.items.discordIntegration.label"),
      hookExtensions: t("adminNav.items.hookExtensions.label"),
      users: t("adminNav.items.users.label"),
      groups: t("adminNav.items.groups.label"),
      scim: t("adminNav.items.scim.label"),
      plansAndBilling: t("adminNav.items.plansAndBilling.label"),
      appearanceAndTheming: t("adminNav.items.appearanceAndTheming.label"),
      securityAndHardening: t("adminNav.items.securityAndHardening.label"),
      ssoProviders: t("adminNav.items.ssoProviders.label"),
      usage: t("adminNav.items.usage.label"),
      analytics: t("adminNav.items.analytics.label"),
      queryHistory: t("adminNav.items.queryHistory.label"),
      tracing: t("adminNav.items.tracing.label"),
      exportLogs: t("adminNav.items.exportLogs.label"),
      upgradePlan: t("adminNav.items.upgradePlan.label"),
    }),
    [t]
  );

  const sectionLabels = useMemo<Record<AdminNavSectionId, string>>(
    () => ({
      craft: t("adminNav.sections.craft.label"),
      agentsAndActions: t("adminNav.sections.agentsAndActions.label"),
      documentsAndKnowledge: t("adminNav.sections.documentsAndKnowledge.label"),
      integrations: t("adminNav.sections.integrations.label"),
      permissions: t("adminNav.sections.permissions.label"),
      organization: t("adminNav.sections.organization.label"),
      usage: t("adminNav.sections.usage.label"),
    }),
    [t]
  );

  // Search the labels the user reads, not the underlying ids.
  const itemExtractor = useCallback(
    (item: SidebarItemEntry) => navLabels[item.nameId],
    [navLabels]
  );

  const { query, setQuery, filtered } = useFilter(allItems, itemExtractor);

  const enabled = filtered.filter((item) => !item.disabled);
  const disabled = filtered.filter((item) => item.disabled);
  const enabledGroups = groupBySection(enabled);
  const disabledGroups = groupBySection(disabled);

  return (
    <SidebarLayouts.Root>
      <SidebarLayouts.Header
        renderAppLogo={renderSidebarLogo}
        showLogoWhenFolded={showLogoWhenFolded}
      >
        {folded ? (
          <SidebarTab
            icon={SvgSearch}
            onClick={() => {
              setFolded(false);
              setFocusSearch(true);
            }}
          >
            {t("adminSidebar.search.label")}
          </SidebarTab>
        ) : (
          <InputTypeIn
            ref={searchRef}
            variant="internal"
            searchIcon
            placeholder={t("adminSidebar.searchInput.placeholder")}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            clearButton
          />
        )}
      </SidebarLayouts.Header>

      <SidebarLayouts.Body scrollKey="admin-sidebar">
        {enabledGroups.map((group, groupIndex) => (
          <React.Fragment key={groupIndex}>
            <SidebarLayouts.Section
              title={
                group.sectionId ? sectionLabels[group.sectionId] : undefined
              }
            >
              {group.items.map(({ link, icon, nameId }) => (
                <SidebarTab
                  key={link}
                  icon={icon}
                  href={link}
                  selected={pathname.startsWith(link)}
                >
                  {navLabels[nameId]}
                </SidebarTab>
              ))}
            </SidebarLayouts.Section>
          </React.Fragment>
        ))}

        {disabledGroups.length > 0 && (
          <>
            <Divider paddingPerpendicular={0} />
            {/* Empty div here just to add spacing (via the `gap` property on `SidebarLayouts.Body`) */}
            <div />
          </>
        )}
        {disabledGroups.map((group, groupIndex) => (
          <React.Fragment key={`disabled-${groupIndex}`}>
            <SidebarLayouts.Section
              title={
                group.sectionId ? sectionLabels[group.sectionId] : undefined
              }
              disabled
            >
              {group.items.map(({ link, icon, nameId, requiredTier }) => (
                <SidebarTab
                  key={link}
                  disabled
                  icon={icon}
                  tooltip={markdown(
                    requiredTier === Tier.ENTERPRISE
                      ? t("adminSidebar.enterpriseOnly.tooltip")
                      : t("adminSidebar.businessOrEnterpriseOnly.tooltip")
                  )}
                >
                  {navLabels[nameId]}
                </SidebarTab>
              ))}
            </SidebarLayouts.Section>
          </React.Fragment>
        ))}
      </SidebarLayouts.Body>

      <SidebarLayouts.Footer>
        {!folded && <Divider paddingPerpendicular={2} />}
        <SidebarTab
          icon={SvgX}
          href={pathname?.startsWith("/admin/craft") ? "/craft/v1" : "/app"}
          variant="sidebar-light"
        >
          {t("adminSidebar.exitAdminPanel.label")}
        </SidebarTab>
        <AccountPopover />
      </SidebarLayouts.Footer>
    </SidebarLayouts.Root>
  );
}
