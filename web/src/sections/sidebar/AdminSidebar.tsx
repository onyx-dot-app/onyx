"use client";

import { usePathname } from "next/navigation";
import { useSettingsContext } from "@/providers/SettingsProvider";
import { CgArrowsExpandUpLeft } from "react-icons/cg";
import Text from "@/refresh-components/texts/Text";
import SidebarSection from "@/sections/sidebar/SidebarSection";
import SidebarWrapper from "@/sections/sidebar/SidebarWrapper";
import { useIsKGExposed } from "@/app/admin/kg/utils";
import { useCustomAnalyticsEnabled } from "@/lib/hooks/useCustomAnalyticsEnabled";
import { useUser } from "@/providers/UserProvider";
import { UserRole } from "@/lib/types";
import {
  useBillingInformation,
  useLicense,
  hasActiveSubscription,
} from "@/lib/billing";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import { CombinedSettings } from "@/interfaces/settings";
import SidebarTab from "@/refresh-components/buttons/SidebarTab";
import SidebarBody from "@/sections/sidebar/SidebarBody";
import {
  SvgActions,
  SvgActivity,
  SvgArrowUpCircle,
  SvgBarChart,
  SvgCpu,
  SvgFileText,
  SvgFolder,
  SvgGlobe,
  SvgArrowExchange,
  SvgImage,
  SvgKey,
  SvgOnyxLogo,
  SvgOnyxOctagon,
  SvgSearch,
  SvgServer,
  SvgSettings,
  SvgShield,
  SvgThumbsUp,
  SvgUploadCloud,
  SvgUser,
  SvgUsers,
  SvgZoomIn,
  SvgPaintBrush,
  SvgDiscordMono,
  SvgWallet,
  SvgAudio,
} from "@opal/icons";
import SvgMcp from "@opal/icons/mcp";
import { ADMIN_PATHS, sidebarItem } from "@/lib/admin-routes";
import UserAvatarPopover from "@/sections/sidebar/UserAvatarPopover";

const connectors_items = () => [
  sidebarItem(ADMIN_PATHS.INDEXING_STATUS),
  sidebarItem(ADMIN_PATHS.ADD_CONNECTOR),
];

const document_management_items = () => [
  sidebarItem(ADMIN_PATHS.DOCUMENT_SETS),
  sidebarItem(ADMIN_PATHS.DOCUMENT_EXPLORER),
  sidebarItem(ADMIN_PATHS.DOCUMENT_FEEDBACK),
];

const custom_agents_items = (isCurator: boolean, enableEnterprise: boolean) => {
  const items = [sidebarItem(ADMIN_PATHS.AGENTS)];

  if (!isCurator) {
    items.push(
      sidebarItem(ADMIN_PATHS.SLACK_BOTS),
      sidebarItem(ADMIN_PATHS.DISCORD_BOTS)
    );
  }

  items.push(
    sidebarItem(ADMIN_PATHS.MCP_ACTIONS),
    sidebarItem(ADMIN_PATHS.OPENAPI_ACTIONS)
  );

  if (enableEnterprise) {
    items.push(sidebarItem(ADMIN_PATHS.STANDARD_ANSWERS));
  }

  return items;
};

const collections = (
  isCurator: boolean,
  enableCloud: boolean,
  enableEnterprise: boolean,
  settings: CombinedSettings | null,
  kgExposed: boolean,
  customAnalyticsEnabled: boolean,
  hasSubscription: boolean
) => {
  const vectorDbEnabled = settings?.settings.vector_db_enabled !== false;

  return [
    ...(vectorDbEnabled
      ? [
          {
            name: "Connectors",
            items: connectors_items(),
          },
        ]
      : []),
    ...(vectorDbEnabled
      ? [
          {
            name: "Document Management",
            items: document_management_items(),
          },
        ]
      : []),
    {
      name: "Custom Agents",
      items: custom_agents_items(isCurator, enableEnterprise),
    },
    ...(isCurator && enableEnterprise
      ? [
          {
            name: "User Management",
            items: [sidebarItem(ADMIN_PATHS.GROUPS)],
          },
        ]
      : []),
    ...(!isCurator
      ? [
          {
            name: "Configuration",
            items: [
              sidebarItem(ADMIN_PATHS.CHAT_PREFERENCES),
              sidebarItem(ADMIN_PATHS.LLM_MODELS),
              sidebarItem(ADMIN_PATHS.WEB_SEARCH),
              sidebarItem(ADMIN_PATHS.IMAGE_GENERATION),
              {
                name: "Voice",
                icon: SvgAudio,
                link: "/admin/configuration/voice",
              },
              sidebarItem(ADMIN_PATHS.CODE_INTERPRETER),
              ...(!enableCloud && vectorDbEnabled
                ? [
                    {
                      ...sidebarItem(ADMIN_PATHS.SEARCH_SETTINGS),
                      error: settings?.settings.needs_reindexing,
                    },
                  ]
                : []),
              sidebarItem(ADMIN_PATHS.DOCUMENT_PROCESSING),
              ...(kgExposed ? [sidebarItem(ADMIN_PATHS.KNOWLEDGE_GRAPH)] : []),
            ],
          },
          {
            name: "User Management",
            items: [
              sidebarItem(ADMIN_PATHS.USERS),
              ...(enableEnterprise ? [sidebarItem(ADMIN_PATHS.GROUPS)] : []),
              sidebarItem(ADMIN_PATHS.API_KEYS),
              sidebarItem(ADMIN_PATHS.TOKEN_RATE_LIMITS),
            ],
          },
          {
            name: "Permissions",
            items: [
              // TODO (nikolas): Uncommented in switchover PR once Users v2 is ready
              // sidebarItem(ADMIN_PATHS.USERS_V2),
              ...(enableEnterprise ? [sidebarItem(ADMIN_PATHS.SCIM)] : []),
            ],
          },
          ...(enableEnterprise
            ? [
                {
                  name: "Performance",
                  items: [
                    sidebarItem(ADMIN_PATHS.USAGE),
                    ...(settings?.settings.query_history_type !== "disabled"
                      ? [sidebarItem(ADMIN_PATHS.QUERY_HISTORY)]
                      : []),
                    ...(!enableCloud && customAnalyticsEnabled
                      ? [sidebarItem(ADMIN_PATHS.CUSTOM_ANALYTICS)]
                      : []),
                  ],
                },
              ]
            : []),
          {
            name: "Settings",
            items: [
              ...(enableEnterprise ? [sidebarItem(ADMIN_PATHS.THEME)] : []),
              // Always show billing/upgrade - community users need access to upgrade
              {
                ...sidebarItem(ADMIN_PATHS.BILLING),
                ...(hasSubscription
                  ? {}
                  : { name: "Upgrade Plan", icon: SvgArrowUpCircle }),
              },
              ...(settings?.settings.opensearch_indexing_enabled
                ? [sidebarItem(ADMIN_PATHS.INDEX_MIGRATION)]
                : []),
            ],
          },
        ]
      : []),
  ];
};

interface AdminSidebarProps {
  // Cloud flag is passed from server component (Layout.tsx) since it's a build-time constant
  enableCloudSS: boolean;
  // Enterprise flag is also passed but we override it with runtime license check below
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
  const { data: billingData } = useBillingInformation();
  const { data: licenseData } = useLicense();

  // Use runtime license check for enterprise features
  // This checks settings.ee_features_enabled (set by backend based on license status)
  // Falls back to build-time check if LICENSE_ENFORCEMENT_ENABLED=false
  const enableEnterprise = usePaidEnterpriseFeaturesEnabled();

  const isCurator =
    user?.role === UserRole.CURATOR || user?.role === UserRole.GLOBAL_CURATOR;

  // Check if user has an active subscription or license for billing link text
  // Show "Plans & Billing" if they have either (even if Stripe connection fails)
  const hasSubscription = Boolean(
    (billingData && hasActiveSubscription(billingData)) ||
      licenseData?.has_license
  );

  const items = collections(
    isCurator,
    enableCloudSS,
    enableEnterprise,
    settings,
    kgExposed,
    customAnalyticsEnabled,
    hasSubscription
  );

  return (
    <SidebarWrapper>
      <SidebarBody
        scrollKey="admin-sidebar"
        actionButtons={
          <SidebarTab
            icon={({ className }) => (
              <CgArrowsExpandUpLeft className={className} size={16} />
            )}
            href="/app"
          >
            Exit Admin
          </SidebarTab>
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
        {items.map((collection, index) => (
          <SidebarSection key={index} title={collection.name}>
            <div className="flex flex-col w-full">
              {collection.items.map(({ link, icon: Icon, name }, index) => (
                <SidebarTab
                  key={index}
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
          </SidebarSection>
        ))}
      </SidebarBody>
    </SidebarWrapper>
  );
}
