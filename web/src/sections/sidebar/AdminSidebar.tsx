"use client";

import { useCallback, useRef, useMemo } from "react";
import { usePathname } from "next/navigation";
import { useSettingsContext } from "@/providers/SettingsProvider";
import Text from "@/refresh-components/texts/Text";
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
import { SvgAudio, SvgX } from "@opal/icons";
import { ADMIN_PATHS, sidebarItem } from "@/lib/admin-routes";
import UserAvatarPopover from "@/sections/sidebar/UserAvatarPopover";
import useFilter from "@/hooks/useFilter";
import { IconFunctionComponent } from "@opal/types";

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

  // 1. No header — core configuration + all remaining tabs
  {
    const items: SidebarItemEntry[] = [
      sidebarItem(ADMIN_PATHS.LLM_MODELS),
      sidebarItem(ADMIN_PATHS.WEB_SEARCH),
      sidebarItem(ADMIN_PATHS.IMAGE_GENERATION),
      {
        name: "Voice",
        icon: SvgAudio,
        link: "/admin/configuration/voice",
      },
      sidebarItem(ADMIN_PATHS.CODE_INTERPRETER),
      sidebarItem(ADMIN_PATHS.CHAT_PREFERENCES),
    ];

    if (vectorDbEnabled && kgExposed) {
      items.push(sidebarItem(ADMIN_PATHS.KNOWLEDGE_GRAPH));
    }

    if (!enableCloud && customAnalyticsEnabled) {
      items.push({
        ...sidebarItem(ADMIN_PATHS.CUSTOM_ANALYTICS),
        disabled: !enableEnterprise,
      });
    }

    if (settings?.settings.opensearch_indexing_enabled) {
      items.push(sidebarItem(ADMIN_PATHS.INDEX_MIGRATION));
    }

    collections.push({ name: "", items });
  }

  // 2. Agents & Actions
  collections.push({
    name: "Agents & Actions",
    items: [
      sidebarItem(ADMIN_PATHS.AGENTS),
      sidebarItem(ADMIN_PATHS.MCP_ACTIONS),
      sidebarItem(ADMIN_PATHS.OPENAPI_ACTIONS),
    ],
  });

  // 3. Documents & Knowledge
  if (vectorDbEnabled) {
    const docsItems: SidebarItemEntry[] = [
      sidebarItem(ADMIN_PATHS.INDEXING_STATUS),
      sidebarItem(ADMIN_PATHS.ADD_CONNECTOR),
      sidebarItem(ADMIN_PATHS.DOCUMENT_SETS),
    ];
    if (!enableCloud) {
      docsItems.push({
        ...sidebarItem(ADMIN_PATHS.SEARCH_SETTINGS),
        error: settings?.settings.needs_reindexing,
      });
    }
    collections.push({ name: "Documents & Knowledge", items: docsItems });
  }

  // 4. Integrations (admin only)
  if (!isCurator) {
    collections.push({
      name: "Integrations",
      items: [
        {
          ...sidebarItem(ADMIN_PATHS.API_KEYS),
          name: "Service Accounts",
        },
        {
          ...sidebarItem(ADMIN_PATHS.SLACK_BOTS),
          name: "Slack Integration",
        },
        {
          ...sidebarItem(ADMIN_PATHS.DISCORD_BOTS),
          name: "Discord Integration",
        },
      ],
    });
  }

  // 5. Permissions
  if (!isCurator) {
    collections.push({
      name: "Permissions",
      items: [
        sidebarItem(ADMIN_PATHS.USERS),
        {
          ...sidebarItem(ADMIN_PATHS.GROUPS),
          disabled: !enableEnterprise,
        },
        {
          ...sidebarItem(ADMIN_PATHS.SCIM),
          disabled: !enableEnterprise,
        },
      ],
    });
  } else if (enableEnterprise) {
    collections.push({
      name: "Permissions",
      items: [sidebarItem(ADMIN_PATHS.GROUPS)],
    });
  }

  // 6. Organization (admin only)
  if (!isCurator) {
    collections.push({
      name: "Organization",
      items: [
        sidebarItem(ADMIN_PATHS.BILLING),
        {
          ...sidebarItem(ADMIN_PATHS.THEME),
          disabled: !enableEnterprise,
        },
      ],
    });
  }

  // 7. Usage
  if (!isCurator) {
    collections.push({
      name: "Usage",
      items: [
        {
          ...sidebarItem(ADMIN_PATHS.USAGE),
          disabled: !enableEnterprise,
        },
        {
          ...sidebarItem(ADMIN_PATHS.QUERY_HISTORY),
          disabled: !enableEnterprise,
        },
        sidebarItem(ADMIN_PATHS.TOKEN_RATE_LIMITS),
      ],
    });
  }

  return collections;
}

interface AdminSidebarProps {
  enableCloudSS: boolean;
  enableEnterpriseSS: boolean;
}

export default function AdminSidebar({
  enableCloudSS,
  enableEnterpriseSS,
}: AdminSidebarProps) {
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
    // Preserve original collection order
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

  // Flat list of visible items for keyboard navigation
  const visibleItems = useMemo(
    () => filteredCollections.flatMap((c) => c.items),
    [filteredCollections]
  );

  const focusIndexRef = useRef(-1);
  const tabRefsRef = useRef<Map<string, HTMLElement>>(new Map());

  const handleSearchKeyDown = (e: React.KeyboardEvent) => {
    if (e.key !== "Tab" || !query) return;

    e.preventDefault();

    const len = visibleItems.length;
    if (len === 0) return;

    if (e.shiftKey) {
      focusIndexRef.current =
        focusIndexRef.current <= 0 ? len - 1 : focusIndexRef.current - 1;
    } else {
      focusIndexRef.current =
        focusIndexRef.current >= len - 1 ? 0 : focusIndexRef.current + 1;
    }

    const item = visibleItems[focusIndexRef.current];
    if (!item) return;
    const el = tabRefsRef.current.get(item.link);
    el?.focus();
  };

  const handleTabKeyDown = (
    e: React.KeyboardEvent,
    itemIndex: number,
    link: string | undefined
  ) => {
    if (e.key === "Enter" && link) {
      window.location.href = link;
      return;
    }

    if (e.key !== "Tab" || !query) return;

    e.preventDefault();

    const len = visibleItems.length;
    if (e.shiftKey) {
      focusIndexRef.current = itemIndex <= 0 ? len - 1 : itemIndex - 1;
    } else {
      focusIndexRef.current = itemIndex >= len - 1 ? 0 : itemIndex + 1;
    }

    const item = visibleItems[focusIndexRef.current];
    if (!item) return;
    const el = tabRefsRef.current.get(item.link);
    el?.focus();
  };

  // Reset focus index when query changes
  const handleQueryChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setQuery(e.target.value);
    focusIndexRef.current = -1;
  };

  // Track running index across collections for keyboard nav
  let runningIndex = 0;

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
              onChange={handleQueryChange}
              onKeyDown={handleSearchKeyDown}
            />
          </div>
        }
        footer={
          <div className="flex flex-col gap-2">
            {settings.webVersion && (
              <Text as="p" text02 secondaryBody className="px-2">
                {`Onyx version: ${settings.webVersion}`}
              </Text>
            )}
            <UserAvatarPopover />
          </div>
        }
      >
        {filteredCollections.map((collection, collectionIndex) => {
          const tabs = (
            <div className="flex flex-col w-full">
              {collection.items.map((item) => {
                const { link, icon: Icon, name, disabled } = item;
                const itemIndex = runningIndex++;

                const tab = (
                  <div
                    key={link}
                    tabIndex={-1}
                    ref={(el) => {
                      if (el) {
                        tabRefsRef.current.set(link, el);
                      } else {
                        tabRefsRef.current.delete(link);
                      }
                    }}
                    onKeyDown={(e) =>
                      handleTabKeyDown(
                        e,
                        itemIndex,
                        disabled ? undefined : link
                      )
                    }
                    className="outline-none"
                  >
                    {disabled ? (
                      <Disabled disabled>
                        <div>
                          <SidebarTab
                            lowlight
                            icon={({ className }) => (
                              <Icon className={className} size={16} />
                            )}
                          >
                            {name}
                          </SidebarTab>
                        </div>
                      </Disabled>
                    ) : (
                      <SidebarTab
                        href={link}
                        selected={pathname.startsWith(link)}
                        icon={({ className }) => (
                          <Icon className={className} size={16} />
                        )}
                      >
                        {name}
                      </SidebarTab>
                    )}
                  </div>
                );

                return tab;
              })}
            </div>
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
