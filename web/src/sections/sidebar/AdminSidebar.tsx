"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { useSettings } from "@/lib/settings/hooks";
import { SidebarLayouts, useSidebarState } from "@opal/layouts";
import { useCustomAnalyticsEnabled } from "@/lib/hooks/useCustomAnalyticsEnabled";
import { useUser } from "@/providers/UserProvider";
import { UserRole } from "@/lib/types";
import { Settings, Tier } from "@/lib/settings/types";
import { tierAtLeast } from "@/lib/tiers";
import { Divider, InputTypeIn, Spacer, SidebarTab } from "@opal/components";
import { SvgArrowUpCircle, SvgSearch, SvgX } from "@opal/icons";
import {
  useBillingInformation,
  useLicense,
  hasActiveSubscription,
} from "@/lib/billing";
import { ADMIN_ROUTES, sidebarItem } from "@/lib/admin-routes";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import useFilter from "@/hooks/useFilter";
import { IconFunctionComponent } from "@opal/types";
import AccountPopover from "@/sections/sidebar/AccountPopover";
import { renderAppLogo } from "@/sections/sidebar/SidebarWrapper";
import { useShowLogoWhenFolded } from "@/lib/sidebar/hooks";
import { markdown } from "@opal/utils";

const SECTIONS = {
  UNLABELED: null,
  AGENTS_AND_ACTIONS: "Agents & Actions",
  DOCUMENTS_AND_KNOWLEDGE: "Documents & Knowledge",
  INTEGRATIONS: "Integrations",
  PERMISSIONS: "Permissions",
  ORGANIZATION: "Organization",
  USAGE: "Usage",
} as const;

interface SidebarItemEntry {
  section: string | null;
  name: string;
  icon: IconFunctionComponent;
  link: string;
  error?: boolean;
  disabled?: boolean;
  requiredTier?: Tier;
}

function buildItems(
  isCurator: boolean,
  enableCloud: boolean,
  tier: Tier | undefined,
  settings: Settings | null,
  customAnalyticsEnabled: boolean,
  hasSubscription: boolean,
  hooksEnabled: boolean
): SidebarItemEntry[] {
  const items: SidebarItemEntry[] = [];

  const add = (
    section: string | null,
    route: Parameters<typeof sidebarItem>[0]
  ) => {
    items.push({ ...sidebarItem(route), section });
  };

  const addGated = (
    section: string | null,
    route: Parameters<typeof sidebarItem>[0],
    requiredTier: Tier
  ) => {
    items.push({
      ...sidebarItem(route),
      section,
      disabled: !tierAtLeast(tier, requiredTier),
      requiredTier,
    });
  };

  // 1. No header — core configuration (admin only)
  if (!isCurator) {
    add(SECTIONS.UNLABELED, ADMIN_ROUTES.LLM_MODELS);
    add(SECTIONS.UNLABELED, ADMIN_ROUTES.WEB_SEARCH);
    add(SECTIONS.UNLABELED, ADMIN_ROUTES.IMAGE_GENERATION);
    add(SECTIONS.UNLABELED, ADMIN_ROUTES.VOICE);
    add(SECTIONS.UNLABELED, ADMIN_ROUTES.CODE_INTERPRETER);
    add(SECTIONS.UNLABELED, ADMIN_ROUTES.CHAT_PREFERENCES);

    if (!enableCloud && customAnalyticsEnabled) {
      addGated(
        SECTIONS.UNLABELED,
        ADMIN_ROUTES.CUSTOM_ANALYTICS,
        Tier.ENTERPRISE
      );
    }
  }

  // 2. Agents & Actions
  add(SECTIONS.AGENTS_AND_ACTIONS, ADMIN_ROUTES.AGENTS);
  add(SECTIONS.AGENTS_AND_ACTIONS, ADMIN_ROUTES.MCP_ACTIONS);
  add(SECTIONS.AGENTS_AND_ACTIONS, ADMIN_ROUTES.OPENAPI_ACTIONS);

  // 3. Documents & Knowledge
  // Shown even in Lite mode; the pages themselves render a no-indexing notice.
  add(SECTIONS.DOCUMENTS_AND_KNOWLEDGE, ADMIN_ROUTES.INDEXING_STATUS);
  add(SECTIONS.DOCUMENTS_AND_KNOWLEDGE, ADMIN_ROUTES.ADD_CONNECTOR);
  add(SECTIONS.DOCUMENTS_AND_KNOWLEDGE, ADMIN_ROUTES.DOCUMENT_SETS);
  if (!isCurator) {
    items.push({
      ...sidebarItem(ADMIN_ROUTES.INDEX_SETTINGS),
      section: SECTIONS.DOCUMENTS_AND_KNOWLEDGE,
      error: settings?.needs_reindexing,
    });
  }

  // 4. Integrations (admin only)
  if (!isCurator) {
    addGated(SECTIONS.INTEGRATIONS, ADMIN_ROUTES.API_KEYS, Tier.BUSINESS);
    add(SECTIONS.INTEGRATIONS, ADMIN_ROUTES.SLACK_BOTS);
    add(SECTIONS.INTEGRATIONS, ADMIN_ROUTES.DISCORD_BOTS);
    if (hooksEnabled) {
      addGated(SECTIONS.INTEGRATIONS, ADMIN_ROUTES.HOOKS, Tier.ENTERPRISE);
    }
  }

  // 5. Permissions
  if (!isCurator) {
    add(SECTIONS.PERMISSIONS, ADMIN_ROUTES.USERS);
    addGated(SECTIONS.PERMISSIONS, ADMIN_ROUTES.GROUPS, Tier.BUSINESS);
    addGated(SECTIONS.PERMISSIONS, ADMIN_ROUTES.SCIM, Tier.ENTERPRISE);
  } else if (tierAtLeast(tier, Tier.BUSINESS)) {
    add(SECTIONS.PERMISSIONS, ADMIN_ROUTES.GROUPS);
  }

  // 6. Usage (admin only)
  if (!isCurator) {
    addGated(SECTIONS.USAGE, ADMIN_ROUTES.USAGE, Tier.BUSINESS);
    addGated(SECTIONS.USAGE, ADMIN_ROUTES.TOKEN_RATE_LIMITS, Tier.ENTERPRISE);
    if (
      settings?.query_history_type !== "disabled" &&
      !settings?.hide_query_history_from_admin_panel
    ) {
      addGated(SECTIONS.USAGE, ADMIN_ROUTES.QUERY_HISTORY, Tier.BUSINESS);
    }
  }

  // 7. Organization (admin only)
  if (!isCurator) {
    addGated(SECTIONS.ORGANIZATION, ADMIN_ROUTES.THEME, Tier.BUSINESS);
    add(SECTIONS.ORGANIZATION, ADMIN_ROUTES.SECURITY_HARDENING);
    if (hasSubscription) {
      add(SECTIONS.ORGANIZATION, ADMIN_ROUTES.BILLING);
    }
  }

  // 8. Upgrade Plan (admin only, no subscription)
  if (!isCurator && !hasSubscription) {
    items.push({
      section: SECTIONS.UNLABELED,
      name: "Upgrade Plan",
      icon: SvgArrowUpCircle,
      link: ADMIN_ROUTES.BILLING.path,
    });
  }

  return items;
}

/** Preserve section ordering while grouping consecutive items by section. */
function groupBySection(items: SidebarItemEntry[]) {
  const groups: { section: string | null; items: SidebarItemEntry[] }[] = [];
  for (const item of items) {
    const last = groups[groups.length - 1];
    if (last && last.section === item.section) {
      last.items.push(item);
    } else {
      groups.push({ section: item.section, items: [item] });
    }
  }
  return groups;
}

export default function AdminSidebar() {
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
  const { user } = useUser();
  const settings = useSettings();
  const tier = settings?.tier;
  const { data: billingData, isLoading: billingLoading } =
    useBillingInformation();
  const { data: licenseData, isLoading: licenseLoading } = useLicense();
  const isCurator =
    user?.role === UserRole.CURATOR || user?.role === UserRole.GLOBAL_CURATOR;
  // Default to true while loading to avoid flashing "Upgrade Plan"
  const hasSubscriptionOrLicense =
    billingLoading || licenseLoading
      ? true
      : Boolean(
          (billingData && hasActiveSubscription(billingData)) ||
          licenseData?.has_license
        );
  // Hooks are ENTERPRISE-only and only available for self-hosted single-tenant.
  const hooksEnabled =
    tierAtLeast(tier, Tier.ENTERPRISE) && (settings?.hooks_enabled ?? false);

  const allItems = buildItems(
    isCurator,
    NEXT_PUBLIC_CLOUD_ENABLED,
    tier,
    settings,
    customAnalyticsEnabled,
    hasSubscriptionOrLicense,
    hooksEnabled
  );

  const itemExtractor = useCallback((item: SidebarItemEntry) => item.name, []);

  const { query, setQuery, filtered } = useFilter(allItems, itemExtractor);

  const enabled = filtered.filter((item) => !item.disabled);
  const disabled = filtered.filter((item) => item.disabled);
  const enabledGroups = groupBySection(enabled);
  const disabledGroups = groupBySection(disabled);

  return (
    <SidebarLayouts.Root>
      <SidebarLayouts.Header
        logo={renderAppLogo}
        showLogoWhenFolded={showLogoWhenFolded}
      >
        {folded ? (
          <SidebarTab
            icon={SvgSearch}
            folded
            onClick={() => {
              setFolded(false);
              setFocusSearch(true);
            }}
          >
            Search
          </SidebarTab>
        ) : (
          <InputTypeIn
            ref={searchRef}
            variant="internal"
            searchIcon
            placeholder="Search..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            clearButton
          />
        )}
      </SidebarLayouts.Header>

      <SidebarLayouts.Body scrollKey="admin-sidebar">
        {enabledGroups.map((group, groupIndex) => (
          <React.Fragment key={groupIndex}>
            <SidebarLayouts.Section title={group.section ?? undefined}>
              {group.items.map(({ link, icon, name }) => (
                <SidebarTab
                  key={link}
                  icon={icon}
                  href={link}
                  selected={pathname.startsWith(link)}
                >
                  {name}
                </SidebarTab>
              ))}
            </SidebarLayouts.Section>
          </React.Fragment>
        ))}

        {disabledGroups.length > 0 && (
          <>
            <Divider paddingPerpendicular="fit" />
            {/* Empty div here just to add spacing (via the `gap` property on `SidebarLayouts.Body`) */}
            <div />
          </>
        )}
        {disabledGroups.map((group, groupIndex) => (
          <React.Fragment key={`disabled-${groupIndex}`}>
            <SidebarLayouts.Section title={group.section ?? undefined} disabled>
              {group.items.map(({ link, icon, name, requiredTier }) => (
                <SidebarTab
                  key={link}
                  disabled
                  icon={icon}
                  tooltip={markdown(
                    requiredTier === Tier.ENTERPRISE
                      ? "This feature is available on the [Enterprise version of Onyx](/admin/billing) only."
                      : "This feature is available on the [Business or Enterprise version of Onyx](/admin/billing) only."
                  )}
                >
                  {name}
                </SidebarTab>
              ))}
            </SidebarLayouts.Section>
          </React.Fragment>
        ))}
      </SidebarLayouts.Body>

      <SidebarLayouts.Footer>
        {!folded && <Divider paddingPerpendicular="sm" />}
        <SidebarTab
          icon={SvgX}
          href="/app"
          variant="sidebar-light"
          folded={folded}
        >
          Exit Admin Panel
        </SidebarTab>
        <AccountPopover folded={folded} />
      </SidebarLayouts.Footer>
    </SidebarLayouts.Root>
  );
}
