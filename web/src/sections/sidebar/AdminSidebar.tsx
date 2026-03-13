"use client";

import { useState, useMemo } from "react";
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
import { SvgAudio, SvgX } from "@opal/icons";
import { ADMIN_PATHS, sidebarItem } from "@/lib/admin-routes";
import UserAvatarPopover from "@/sections/sidebar/UserAvatarPopover";
import { IconFunctionComponent } from "@opal/types";

interface SidebarItemEntry {
  name: string;
  icon: IconFunctionComponent;
  link: string;
  error?: boolean;
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

    if (vectorDbEnabled) {
      items.push(
        sidebarItem(ADMIN_PATHS.DOCUMENT_SETS),
        sidebarItem(ADMIN_PATHS.DOCUMENT_EXPLORER),
        sidebarItem(ADMIN_PATHS.DOCUMENT_FEEDBACK),
        sidebarItem(ADMIN_PATHS.DOCUMENT_PROCESSING)
      );
      if (kgExposed) {
        items.push(sidebarItem(ADMIN_PATHS.KNOWLEDGE_GRAPH));
      }
    }

    if (enableEnterprise) {
      items.push(sidebarItem(ADMIN_PATHS.STANDARD_ANSWERS));
    }

    items.push(
      sidebarItem(ADMIN_PATHS.API_KEYS),
      sidebarItem(ADMIN_PATHS.TOKEN_RATE_LIMITS)
    );

    if (!enableCloud && customAnalyticsEnabled && enableEnterprise) {
      items.push(sidebarItem(ADMIN_PATHS.CUSTOM_ANALYTICS));
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
        sidebarItem(ADMIN_PATHS.SLACK_BOTS),
        sidebarItem(ADMIN_PATHS.DISCORD_BOTS),
      ],
    });
  }

  // 5. Permissions
  if (!isCurator) {
    const permissionsItems: SidebarItemEntry[] = [
      sidebarItem(ADMIN_PATHS.USERS),
    ];
    if (enableEnterprise) {
      permissionsItems.push(sidebarItem(ADMIN_PATHS.GROUPS));
      permissionsItems.push(sidebarItem(ADMIN_PATHS.SCIM));
    }
    collections.push({ name: "Permissions", items: permissionsItems });
  } else if (isCurator && enableEnterprise) {
    collections.push({
      name: "Permissions",
      items: [sidebarItem(ADMIN_PATHS.GROUPS)],
    });
  }

  // 6. Organization (admin only)
  if (!isCurator) {
    const orgItems: SidebarItemEntry[] = [sidebarItem(ADMIN_PATHS.BILLING)];
    if (enableEnterprise) {
      orgItems.push(sidebarItem(ADMIN_PATHS.THEME));
    }
    collections.push({ name: "Organization", items: orgItems });
  }

  // 7. Usage (admin + enterprise only)
  if (!isCurator && enableEnterprise) {
    collections.push({
      name: "Usage",
      items: [
        sidebarItem(ADMIN_PATHS.USAGE),
        sidebarItem(ADMIN_PATHS.QUERY_HISTORY),
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
  const [searchQuery, setSearchQuery] = useState("");

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

  const filteredCollections = useMemo(() => {
    const query = searchQuery.toLowerCase().trim();
    if (!query) return allCollections;

    return allCollections
      .map((collection) => ({
        ...collection,
        items: collection.items.filter((item) =>
          item.name.toLowerCase().includes(query)
        ),
      }))
      .filter((collection) => collection.items.length > 0);
  }, [allCollections, searchQuery]);

  return (
    <SidebarWrapper>
      <SidebarBody
        scrollKey="admin-sidebar"
        actionButtons={
          <div className="flex flex-col gap-2 w-full">
            <SidebarTab
              icon={({ className }) => <SvgX className={className} size={16} />}
              href="/app"
              lowlight
            >
              Exit Admin Panel
            </SidebarTab>
            <InputTypeIn
              leftSearchIcon
              placeholder="Search..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
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
        {filteredCollections.map((collection, index) => {
          const tabs = (
            <div className="flex flex-col w-full">
              {collection.items.map(({ link, icon: Icon, name }, i) => (
                <SidebarTab
                  key={i}
                  href={link}
                  selected={pathname.startsWith(link)}
                  icon={({ className }) => (
                    <Icon className={className} size={16} />
                  )}
                >
                  {name}
                </SidebarTab>
              ))}
            </div>
          );

          if (!collection.name) {
            return <div key={index}>{tabs}</div>;
          }

          return (
            <SidebarSection key={index} title={collection.name}>
              {tabs}
            </SidebarSection>
          );
        })}
      </SidebarBody>
    </SidebarWrapper>
  );
}
