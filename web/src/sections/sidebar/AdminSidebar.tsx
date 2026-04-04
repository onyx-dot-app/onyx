"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import { usePathname } from "next/navigation";
import { useSettingsContext } from "@/providers/SettingsProvider";
import SidebarSection from "@/sections/sidebar/SidebarSection";
import * as SidebarLayouts from "@/layouts/sidebar-layouts";
import { useSidebarFolded } from "@/layouts/sidebar-layouts";
import { useIsKGExposed } from "@/app/admin/kg/utils";
import { useCustomAnalyticsEnabled } from "@/lib/hooks/useCustomAnalyticsEnabled";
import { useUser } from "@/providers/UserProvider";
import { UserRole } from "@/lib/types";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import { CombinedSettings } from "@/interfaces/settings";
import { SidebarTab } from "@opal/components";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import Separator from "@/refresh-components/Separator";
import Spacer from "@/refresh-components/Spacer";
import { SvgArrowUpCircle, SvgSearch, SvgX } from "@opal/icons";
import {
  useBillingInformation,
  useLicense,
  hasActiveSubscription,
} from "@/lib/billing";
import { ADMIN_ROUTES, sidebarItem } from "@/lib/admin-routes";
import useFilter from "@/hooks/useFilter";
import { IconFunctionComponent } from "@opal/types";
import AccountPopover from "@/sections/sidebar/AccountPopover";

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
    }
    addDisabled(
      SECTIONS.ORGANIZATION,
      ADMIN_ROUTES.TOKEN_RATE_LIMITS,
      !enableEnterprise
    );
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
  folded: boolean;
  onFoldChange: Dispatch<SetStateAction<boolean>>;
}

interface AdminSidebarInnerProps {
  enableCloudSS: boolean;
  onFoldChange: Dispatch<SetStateAction<boolean>>;
}

function AdminSidebarInner({
  enableCloudSS,
  onFoldChange,
}: AdminSidebarInnerProps) {
  const folded = useSidebarFolded();
  const searchRef = useRef<HTMLInputElement>(null);
  const [focusSearch, setFocusSearch] = useState(false);

  useEffect(() => {
    if (focusSearch && !folded && searchRef.current) {
      searchRef.current.focus();
      setFocusSearch(false);
    }
  }, [focusSearch, folded]);
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
  const hooksEnabled =
    enableEnterprise && (settings?.settings.hooks_enabled ?? false);

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

  const enabled = filtered.filter((item) => !item.disabled);
  const disabled = filtered.filter((item) => item.disabled);
  const enabledGroups = groupBySection(enabled);
  const disabledGroups = groupBySection(disabled);

  return (
    <>
      <SidebarLayouts.Header>
        {folded ? (
          <SidebarTab
            icon={SvgSearch}
            folded
            onClick={() => {
              onFoldChange(false);
              setFocusSearch(true);
            }}
          >
            Search
          </SidebarTab>
        ) : (
          <InputTypeIn
            ref={searchRef}
            variant="internal"
            leftSearchIcon
            placeholder="Search..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        )}
      </SidebarLayouts.Header>

      <SidebarLayouts.Body scrollKey="admin-sidebar">
        {enabledGroups.map((group, groupIndex) => {
          const tabs = group.items.map(({ link, icon, name }) => (
            <SidebarTab
              key={link}
              icon={icon}
              href={link}
              selected={pathname.startsWith(link)}
            >
              {name}
            </SidebarTab>
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

        {disabledGroups.length > 0 && <Separator noPadding className="px-2" />}

        {disabledGroups.map((group, groupIndex) => (
          <SidebarSection
            key={`disabled-${groupIndex}`}
            title={group.section}
            disabled
          >
            {group.items.map(({ link, icon, name }) => (
              <SidebarTab key={link} disabled icon={icon}>
                {name}
              </SidebarTab>
            ))}
          </SidebarSection>
        ))}
      </SidebarLayouts.Body>

      <SidebarLayouts.Footer>
        {!folded && (
          <>
            <Separator noPadding className="px-2" />
            <Spacer rem={0.5} />
          </>
        )}
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
    </>
  );
}

export default function AdminSidebar({
  enableCloudSS,
  folded,
  onFoldChange,
}: AdminSidebarProps) {
  return (
    <SidebarLayouts.Root folded={folded} onFoldChange={onFoldChange}>
      <AdminSidebarInner
        enableCloudSS={enableCloudSS}
        onFoldChange={onFoldChange}
      />
    </SidebarLayouts.Root>
  );
}
