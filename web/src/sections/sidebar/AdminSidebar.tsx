"use client";

import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useAdminNavLabels } from "@/lib/adminNavLabels";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { useSettings } from "@/lib/settings/hooks";
import { SidebarLayouts, useSidebarState } from "@opal/layouts";
import { useUser } from "@/providers/UserProvider";
import { InputTypeIn, SidebarTab, Tag, type TagProps } from "@opal/components";
import { SvgSearch, SvgX } from "@opal/icons";
import { Disabled } from "@opal/core";
import {
  useBillingInformation,
  useLicense,
  hasActiveSubscription,
} from "@/lib/billing";
import {
  CUSTOM_ANALYTICS_ENABLED,
  NEXT_PUBLIC_CLOUD_ENABLED,
} from "@/lib/constants";
import { Tier } from "@/lib/tiers/types";
import { useBetaTag, usePlans } from "@/lib/tiers/hooks";
import useFilter from "@/hooks/useFilter";
import AccountPopover from "@/sections/sidebar/AccountPopover";
import {
  BETA_SECTION_IDS,
  buildItems,
  groupBySection,
  type AdminNavSectionId,
  type FeatureFlags,
  type SidebarItemEntry,
} from "@/lib/admin-sidebar-utils";
import { SidebarLogoMark, SidebarWordmark } from "@/lib/app/components";
import { useShowLogoWhenFolded } from "@/lib/sidebar/hooks";

export default function AdminSidebar() {
  const t = useTranslations("sidebar");
  const plans = usePlans();
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
    customAnalyticsEnabled: CUSTOM_ANALYTICS_ENABLED,
    hasSubscription: hasSubscriptionOrLicense,
    hooksEnabled: settings?.hooks_enabled ?? false,
    queryHistoryEnabled:
      settings?.query_history_type !== "disabled" &&
      !settings?.hide_query_history_from_admin_panel,
    craftAvailable: settings?.onyx_craft_available ?? false,
  };

  const allItems = buildItems(adminCapabilities, flags, settings);

  // Built with literal keys so the message ids stay statically checkable.
  const navLabels = useAdminNavLabels();

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

  const betaTag: TagProps = useBetaTag();
  const sectionTag = (sectionId: AdminNavSectionId | null) =>
    sectionId && BETA_SECTION_IDS.has(sectionId) ? betaTag : undefined;
  const itemTag = (beta: boolean | undefined) =>
    beta ? <Tag {...betaTag} /> : undefined;

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
        logo={<SidebarLogoMark size={28} />}
        wordmark={<SidebarWordmark size={28} />}
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
              tag={sectionTag(group.sectionId)}
            >
              {group.items.map(({ link, icon, nameId, beta }) => (
                <SidebarTab
                  key={link}
                  icon={icon}
                  href={link}
                  selected={pathname.startsWith(link)}
                  rightChildren={itemTag(beta)}
                >
                  {navLabels[nameId]}
                </SidebarTab>
              ))}
            </SidebarLayouts.Section>
          </React.Fragment>
        ))}

        {disabledGroups.length > 0 && <SidebarLayouts.Divider />}
        {disabledGroups.length > 0 && (
          <Disabled
            disabled
            // One tooltip over a tall block: it stays level with the pointer.
            tooltipAlign="follow"
            tooltip={
              plans[
                disabled.every((item) => item.requiredTier === Tier.ENTERPRISE)
                  ? Tier.ENTERPRISE
                  : Tier.BUSINESS
              ].tooltip
            }
          >
            {disabledGroups.map((group, groupIndex) => (
              <SidebarLayouts.Section
                key={`disabled-${groupIndex}`}
                title={
                  group.sectionId ? sectionLabels[group.sectionId] : undefined
                }
                tag={sectionTag(group.sectionId)}
              >
                {group.items.map(({ link, icon, nameId, beta }) => (
                  <SidebarTab
                    key={link}
                    icon={icon}
                    rightChildren={itemTag(beta)}
                  >
                    {navLabels[nameId]}
                  </SidebarTab>
                ))}
              </SidebarLayouts.Section>
            ))}
          </Disabled>
        )}
      </SidebarLayouts.Body>

      <SidebarLayouts.Footer>
        {!folded && <SidebarLayouts.Divider />}
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
