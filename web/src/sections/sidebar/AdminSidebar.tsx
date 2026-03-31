"use client";

import { useCallback } from "react";
import { usePathname } from "next/navigation";
import { useSettingsContext } from "@/providers/SettingsProvider";
import SidebarSection from "@/sections/sidebar/SidebarSection";
import SidebarWrapper from "@/sections/sidebar/SidebarWrapper";
import { useIsKGExposed } from "@/app/admin/kg/utils";
import { useCustomAnalyticsEnabled } from "@/lib/hooks/useCustomAnalyticsEnabled";
import { useUser } from "@/providers/UserProvider";
import { UserRole } from "@/lib/types";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import { CombinedSettings } from "@/interfaces/settings";
import SidebarTab from "@/refresh-components/buttons/SidebarTab";
import SidebarBody from "@/sections/sidebar/SidebarBody";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import { Disabled } from "@opal/core";
import { SvgArrowUpCircle, SvgUserManage, SvgX } from "@opal/icons";
import {
  useBillingInformation,
  useLicense,
  hasActiveSubscription,
} from "@/lib/billing";
import { Content } from "@opal/layouts";
import { ADMIN_ROUTES, sidebarItem } from "@/lib/admin-routes";
import useFilter from "@/hooks/useFilter";
import { IconFunctionComponent } from "@opal/types";
import { Section } from "@/layouts/general-layouts";
import Text from "@/refresh-components/texts/Text";
import { getUserDisplayName } from "@/lib/user";
import { APP_SLOGAN } from "@/lib/constants";

const SECTIONS = {
  UNLABELED: "",
  AGENTS_AND_ACTIONS: "Agents & Actions",
  DOCUMENTS_AND_KNOWLEDGE: "Documents & Knowledge",
  INTEGRATIONS: "Integrations",
  PERMISSIONS: "Permissions",
  ORGANIZATION: "Organization",
  USAGE: "Usage",
} as const;

interface SidebarItemEntry {
  section: string;
  name: string;
  icon: IconFunctionComponent;
  link: string;
  error?: boolean;
  disabled?: boolean;
}

function buildItems(
  isCurator: boolean,
  enableCloud: boolean,
  enableEnterprise: boolean,
  settings: CombinedSettings | null,
  kgExposed: boolean,
  customAnalyticsEnabled: boolean,
  hasSubscription: boolean,
  hooksEnabled: boolean
): SidebarItemEntry[] {
  const vectorDbEnabled = settings?.settings.vector_db_enabled !== false;
  const items: SidebarItemEntry[] = [];

  const add = (section: string, route: Parameters<typeof sidebarItem>[0]) => {
    items.push({ ...sidebarItem(route), section });
  };

  const addDisabled = (
    section: string,
    route: Parameters<typeof sidebarItem>[0],
    isDisabled: boolean
  ) => {
    items.push({ ...sidebarItem(route), section, disabled: isDisabled });
  };

  // 1. No header — core configuration (admin only)
  if (!isCurator) {
    add(SECTIONS.UNLABELED, ADMIN_ROUTES.LLM_MODELS);
    add(SECTIONS.UNLABELED, ADMIN_ROUTES.WEB_SEARCH);
    add(SECTIONS.UNLABELED, ADMIN_ROUTES.IMAGE_GENERATION);
    add(SECTIONS.UNLABELED, ADMIN_ROUTES.VOICE);
    add(SECTIONS.UNLABELED, ADMIN_ROUTES.CODE_INTERPRETER);
    add(SECTIONS.UNLABELED, ADMIN_ROUTES.CHAT_PREFERENCES);

    if (vectorDbEnabled && kgExposed) {
      add(SECTIONS.UNLABELED, ADMIN_ROUTES.KNOWLEDGE_GRAPH);
    }

    if (!enableCloud && customAnalyticsEnabled) {
      addDisabled(
        SECTIONS.UNLABELED,
        ADMIN_ROUTES.CUSTOM_ANALYTICS,
        !enableEnterprise
      );
    }
  }

  // 2. Agents & Actions
  add(SECTIONS.AGENTS_AND_ACTIONS, ADMIN_ROUTES.AGENTS);
  add(SECTIONS.AGENTS_AND_ACTIONS, ADMIN_ROUTES.MCP_ACTIONS);
  add(SECTIONS.AGENTS_AND_ACTIONS, ADMIN_ROUTES.OPENAPI_ACTIONS);

  // 3. Documents & Knowledge
  if (vectorDbEnabled) {
    add(SECTIONS.DOCUMENTS_AND_KNOWLEDGE, ADMIN_ROUTES.INDEXING_STATUS);
    add(SECTIONS.DOCUMENTS_AND_KNOWLEDGE, ADMIN_ROUTES.ADD_CONNECTOR);
    add(SECTIONS.DOCUMENTS_AND_KNOWLEDGE, ADMIN_ROUTES.DOCUMENT_SETS);
    if (!isCurator && !enableCloud) {
      items.push({
        ...sidebarItem(ADMIN_ROUTES.INDEX_SETTINGS),
        section: SECTIONS.DOCUMENTS_AND_KNOWLEDGE,
        error: settings?.settings.needs_reindexing,
      });
    }
    if (!isCurator && settings?.settings.opensearch_indexing_enabled) {
      add(SECTIONS.DOCUMENTS_AND_KNOWLEDGE, ADMIN_ROUTES.INDEX_MIGRATION);
    }
  }

  // 4. Integrations (admin only)
  if (!isCurator) {
    add(SECTIONS.INTEGRATIONS, ADMIN_ROUTES.API_KEYS);
    add(SECTIONS.INTEGRATIONS, ADMIN_ROUTES.SLACK_BOTS);
    add(SECTIONS.INTEGRATIONS, ADMIN_ROUTES.DISCORD_BOTS);
    if (hooksEnabled) {
      add(SECTIONS.INTEGRATIONS, ADMIN_ROUTES.HOOKS);
    }
  }

  // 5. Permissions
  if (!isCurator) {
    add(SECTIONS.PERMISSIONS, ADMIN_ROUTES.USERS);
    addDisabled(SECTIONS.PERMISSIONS, ADMIN_ROUTES.GROUPS, !enableEnterprise);
    addDisabled(SECTIONS.PERMISSIONS, ADMIN_ROUTES.SCIM, !enableEnterprise);
  } else if (enableEnterprise) {
    add(SECTIONS.PERMISSIONS, ADMIN_ROUTES.GROUPS);
  }

  // 6. Organization (admin only)
  if (!isCurator) {
    if (hasSubscription) {
      add(SECTIONS.ORGANIZATION, ADMIN_ROUTES.BILLING);
    } else {
      items.push({
        section: SECTIONS.ORGANIZATION,
        name: "Upgrade Plan",
        icon: SvgArrowUpCircle,
        link: ADMIN_ROUTES.BILLING.path,
      });
    }
    add(SECTIONS.ORGANIZATION, ADMIN_ROUTES.TOKEN_RATE_LIMITS);
    addDisabled(SECTIONS.ORGANIZATION, ADMIN_ROUTES.THEME, !enableEnterprise);
  }

  // 7. Usage (admin only)
  if (!isCurator) {
    addDisabled(SECTIONS.USAGE, ADMIN_ROUTES.USAGE, !enableEnterprise);
    if (settings?.settings.query_history_type !== "disabled") {
      addDisabled(
        SECTIONS.USAGE,
        ADMIN_ROUTES.QUERY_HISTORY,
        !enableEnterprise
      );
    }
  }

  return items;
}

/** Preserve section ordering while grouping consecutive items by section. */
function groupBySection(items: SidebarItemEntry[]) {
  const groups: { section: string; items: SidebarItemEntry[] }[] = [];
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

interface AdminSidebarProps {
  enableCloudSS: boolean;
}

export default function AdminSidebar({ enableCloudSS }: AdminSidebarProps) {
  const { kgExposed } = useIsKGExposed();
  const pathname = usePathname();
  const { customAnalyticsEnabled } = useCustomAnalyticsEnabled();
  const { user } = useUser();
  const settings = useSettingsContext();
  const enableEnterprise = usePaidEnterpriseFeaturesEnabled();
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
  const hooksEnabled = settings?.settings.hooks_enabled ?? false;

  const allItems = buildItems(
    isCurator,
    enableCloudSS,
    enableEnterprise,
    settings,
    kgExposed,
    customAnalyticsEnabled,
    hasSubscriptionOrLicense,
    hooksEnabled
  );

  const itemExtractor = useCallback((item: SidebarItemEntry) => item.name, []);

  const { query, setQuery, filtered } = useFilter(allItems, itemExtractor);

  const groups = groupBySection(filtered);

  return (
    <SidebarWrapper>
      <SidebarBody
        scrollKey="admin-sidebar"
        pinnedContent={
          <div className="flex flex-col w-full">
            <SidebarTab
              icon={({ className }) => <SvgX className={className} size={16} />}
              href="/app"
              lowlight
            >
              Exit Admin Panel
            </SidebarTab>
            <InputTypeIn
              variant="internal"
              leftSearchIcon
              placeholder="Search..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
        }
        footer={
          <Section gap={0} height="fit" alignItems="start">
            <div className="p-[0.38rem] w-full">
              <Content
                icon={SvgUserManage}
                title={getUserDisplayName(user)}
                sizePreset="main-ui"
                variant="body"
                prominence="muted"
                widthVariant="full"
              />
            </div>
            <div className="flex flex-row gap-1 p-[0.38rem] w-full">
              <Text text03 secondaryAction>
                <a
                  className="underline"
                  href="https://onyx.app"
                  target="_blank"
                >
                  Onyx
                </a>
              </Text>
              <Text text03 secondaryBody>
                |
              </Text>
              {settings.webVersion ? (
                <Text text03 secondaryBody>
                  {settings.webVersion}
                </Text>
              ) : (
                <Text text03 secondaryBody>
                  {APP_SLOGAN}
                </Text>
              )}
            </div>
          </Section>
        }
      >
        {groups.map((group, groupIndex) => {
          const tabs = group.items.map(({ link, icon, name, disabled }) => (
            <Disabled key={link} disabled={disabled}>
              {/*
                # NOTE (@raunakab)
                We intentionally add a `div` intermediary here.
                Without it, the disabled styling that is default provided by the `Disabled` component (which we want here) would be overridden by the custom disabled styling provided by the `SidebarTab`.
                Therefore, in order to avoid that overriding, we add a layer of indirection.
              */}
              <div>
                <SidebarTab
                  lowlight={disabled}
                  icon={icon}
                  href={disabled ? undefined : link}
                  selected={!disabled && pathname.startsWith(link)}
                >
                  {name}
                </SidebarTab>
              </div>
            </Disabled>
          ));

          if (!group.section) {
            return <div key={groupIndex}>{tabs}</div>;
          }

          return (
            <SidebarSection key={groupIndex} title={group.section}>
              {tabs}
            </SidebarSection>
          );
        })}
      </SidebarBody>
    </SidebarWrapper>
  );
}
