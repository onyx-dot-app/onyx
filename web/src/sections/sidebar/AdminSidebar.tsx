"use client";

import { useCallback, useMemo } from "react";
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
import { SvgUserManage, SvgX } from "@opal/icons";
import { Content } from "@opal/layouts";
import { ADMIN_ROUTES, sidebarItem } from "@/lib/admin-routes";
import useFilter from "@/hooks/useFilter";
import { IconFunctionComponent } from "@opal/types";
import { Section } from "@/layouts/general-layouts";
import Text from "@/refresh-components/texts/Text";
import { getUserDisplayName } from "@/lib/user";
import { APP_SLOGAN } from "@/lib/constants";

interface SidebarItemEntry {
  name: string;
  icon: IconFunctionComponent;
  link: string;
  error?: boolean;
  disabled?: boolean;
}

interface SidebarCollection {
  name: string;
  items: SidebarItemEntry[];
}

function buildCollections(
  isCurator: boolean,
  enableCloud: boolean,
  enableEnterprise: boolean,
  settings: CombinedSettings | null,
  kgExposed: boolean,
  customAnalyticsEnabled: boolean
): SidebarCollection[] {
  const vectorDbEnabled = settings?.settings.vector_db_enabled !== false;

  const collections: SidebarCollection[] = [];

  // 1. No header — core configuration + remaining tabs (admin only)
  if (!isCurator) {
    const items: SidebarItemEntry[] = [
      sidebarItem(ADMIN_ROUTES.LLM_MODELS),
      sidebarItem(ADMIN_ROUTES.WEB_SEARCH),
      sidebarItem(ADMIN_ROUTES.IMAGE_GENERATION),
      sidebarItem(ADMIN_ROUTES.VOICE),
      sidebarItem(ADMIN_ROUTES.CODE_INTERPRETER),
      sidebarItem(ADMIN_ROUTES.CHAT_PREFERENCES),
    ];

    if (vectorDbEnabled && kgExposed) {
      items.push(sidebarItem(ADMIN_ROUTES.KNOWLEDGE_GRAPH));
    }

    if (!enableCloud && customAnalyticsEnabled) {
      items.push({
        ...sidebarItem(ADMIN_ROUTES.CUSTOM_ANALYTICS),
        disabled: !enableEnterprise,
      });
    }

    collections.push({ name: "", items });
  }

  // 2. Agents & Actions
  collections.push({
    name: "Agents & Actions",
    items: [
      sidebarItem(ADMIN_ROUTES.AGENTS),
      sidebarItem(ADMIN_ROUTES.MCP_ACTIONS),
      sidebarItem(ADMIN_ROUTES.OPENAPI_ACTIONS),
    ],
  });

  // 3. Documents & Knowledge
  if (vectorDbEnabled) {
    const docsItems: SidebarItemEntry[] = [
      sidebarItem(ADMIN_ROUTES.INDEXING_STATUS),
      sidebarItem(ADMIN_ROUTES.ADD_CONNECTOR),
      sidebarItem(ADMIN_ROUTES.DOCUMENT_SETS),
    ];
    if (!isCurator && !enableCloud) {
      docsItems.push({
        ...sidebarItem(ADMIN_ROUTES.SEARCH_SETTINGS),
        error: settings?.settings.needs_reindexing,
      });
    }
    if (!isCurator && settings?.settings.opensearch_indexing_enabled) {
      docsItems.push(sidebarItem(ADMIN_ROUTES.INDEX_MIGRATION));
    }
    collections.push({ name: "Documents & Knowledge", items: docsItems });
  }

  // 4. Integrations (admin only)
  if (!isCurator) {
    collections.push({
      name: "Integrations",
      items: [
        sidebarItem(ADMIN_ROUTES.API_KEYS),
        sidebarItem(ADMIN_ROUTES.SLACK_BOTS),
        sidebarItem(ADMIN_ROUTES.DISCORD_BOTS),
      ],
    });
  }

  // 5. Permissions
  if (!isCurator) {
    collections.push({
      name: "Permissions",
      items: [
        sidebarItem(ADMIN_ROUTES.USERS),
        {
          ...sidebarItem(ADMIN_ROUTES.GROUPS),
          disabled: !enableEnterprise,
        },
        {
          ...sidebarItem(ADMIN_ROUTES.SCIM),
          disabled: !enableEnterprise,
        },
      ],
    });
  } else if (enableEnterprise) {
    collections.push({
      name: "Permissions",
      items: [sidebarItem(ADMIN_ROUTES.GROUPS)],
    });
  }

  // 6. Organization (admin only)
  if (!isCurator) {
    collections.push({
      name: "Organization",
      items: [
        sidebarItem(ADMIN_ROUTES.BILLING),
        {
          ...sidebarItem(ADMIN_ROUTES.THEME),
          disabled: !enableEnterprise,
        },
      ],
    });
  }

  // 7. Usage (admin only)
  if (!isCurator) {
    const usageItems: SidebarItemEntry[] = [
      {
        ...sidebarItem(ADMIN_ROUTES.USAGE),
        disabled: !enableEnterprise,
      },
    ];
    if (settings?.settings.query_history_type !== "disabled") {
      usageItems.push({
        ...sidebarItem(ADMIN_ROUTES.QUERY_HISTORY),
        disabled: !enableEnterprise,
      });
    }
    usageItems.push(sidebarItem(ADMIN_ROUTES.TOKEN_RATE_LIMITS));
    collections.push({ name: "Usage", items: usageItems });
  }

  return collections;
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
  const isCurator =
    user?.role === UserRole.CURATOR || user?.role === UserRole.GLOBAL_CURATOR;

  const allCollections = buildCollections(
    isCurator,
    enableCloudSS,
    enableEnterprise,
    settings,
    kgExposed,
    customAnalyticsEnabled
  );

  // Flatten all items for filtering, then reconstruct collections
  const allItems = useMemo(
    () =>
      allCollections.flatMap((collection) =>
        collection.items.map((item) => ({
          ...item,
          _collectionName: collection.name,
        }))
      ),
    [allCollections]
  );

  const itemExtractor = useCallback(
    (item: SidebarItemEntry & { _collectionName: string }) => item.name,
    []
  );

  const {
    query,
    setQuery,
    filtered: filteredItems,
  } = useFilter(allItems, itemExtractor);

  const filteredCollections = useMemo(() => {
    const collectionMap = new Map<string, SidebarItemEntry[]>();
    for (const collection of allCollections) {
      collectionMap.set(collection.name, []);
    }
    for (const item of filteredItems) {
      const { _collectionName, ...entry } = item;
      collectionMap.get(_collectionName)!.push(entry);
    }
    return allCollections
      .map((c) => ({ name: c.name, items: collectionMap.get(c.name)! }))
      .filter((c) => c.items.length > 0);
  }, [allCollections, filteredItems]);

  return (
    <SidebarWrapper>
      <SidebarBody
        scrollKey="admin-sidebar"
        actionButtons={
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
        {filteredCollections.map((collection, collectionIndex) => {
          const tabs = collection.items.map(
            ({ link, icon, name, disabled }) => (
              <Disabled key={link} disabled={disabled}>
                <SidebarTab
                  lowlight={disabled}
                  icon={icon}
                  href={disabled ? undefined : link}
                  selected={!disabled && pathname.startsWith(link)}
                >
                  {name}
                </SidebarTab>
              </Disabled>
            )
          );

          if (!collection.name) {
            return <div key={collectionIndex}>{tabs}</div>;
          }

          return (
            <SidebarSection key={collectionIndex} title={collection.name}>
              {tabs}
            </SidebarSection>
          );
        })}
      </SidebarBody>
    </SidebarWrapper>
  );
}
