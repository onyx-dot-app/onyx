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
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import { SidebarTab } from "@opal/components";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import Separator from "@/refresh-components/Separator";
import Spacer from "@/refresh-components/Spacer";
import { SvgSearch, SvgX } from "@opal/icons";
import {
  useBillingInformation,
  useLicense,
  hasActiveSubscription,
} from "@/lib/billing";
import useFilter from "@/hooks/useFilter";
import AccountPopover from "@/sections/sidebar/AccountPopover";
import {
  buildItems,
  groupBySection,
  type FeatureFlags,
  type SidebarItemEntry,
} from "@/lib/admin-sidebar-utils";

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
  const { permissions } = useUser();
  const settings = useSettingsContext();
  const enableEnterprise = usePaidEnterpriseFeaturesEnabled();
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

  const flags: FeatureFlags = {
    vectorDbEnabled: settings?.settings.vector_db_enabled !== false,
    kgExposed,
    enableCloud: enableCloudSS,
    enableEnterprise,
    customAnalyticsEnabled,
    hasSubscription: hasSubscriptionOrLicense,
    hooksEnabled:
      enableEnterprise && (settings?.settings.hooks_enabled ?? false),
    opensearchEnabled: settings?.settings.opensearch_indexing_enabled ?? false,
    queryHistoryEnabled: settings?.settings.query_history_type !== "disabled",
  };

  const allItems = buildItems(permissions, flags, settings);

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
