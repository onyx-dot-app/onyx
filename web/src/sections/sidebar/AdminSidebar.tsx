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
import {
  ClipboardIcon,
  NotebookIconSkeleton,
  SlackIconSkeleton,
  BrainIcon,
} from "@/components/icons/icons";
import { CombinedSettings } from "@/interfaces/settings";
import SidebarTab from "@/refresh-components/buttons/SidebarTab";
import SidebarBody from "@/sections/sidebar/SidebarBody";
import {
  SvgActions,
  SvgActivity,
  SvgArrowUpCircle,
  SvgBarChart,
  SvgBubbleText,
  SvgCpu,
  SvgFileText,
  SvgFolder,
  SvgGlobe,
  SvgArrowExchange,
  SvgImage,
  SvgKey,
  SvgOnyxOctagon,
  SvgSearch,
  SvgServer,
  SvgShield,
  SvgThumbsUp,
  SvgUploadCloud,
  SvgUser,
  SvgUsers,
  SvgZoomIn,
  SvgPaintBrush,
  SvgDiscordMono,
  SvgWallet,
  SvgTerminal,
} from "@opal/icons";
import SvgMcp from "@opal/icons/mcp";
import UserAvatarPopover from "@/sections/sidebar/UserAvatarPopover";

const connectors_items = () => [
  {
    name: "Existing Connectors",
    icon: NotebookIconSkeleton,
    link: "/admin/indexing/status",
  },
  {
    name: "Add Connector",
    icon: SvgUploadCloud,
    link: "/admin/add-connector",
  },
];

const document_management_items = () => [
  {
    name: "Document Sets",
    icon: SvgFolder,
    link: "/admin/documents/sets",
  },
  {
    name: "Explorer",
    icon: SvgZoomIn,
    link: "/admin/documents/explorer",
  },
  {
    name: "Feedback",
    icon: SvgThumbsUp,
    link: "/admin/documents/feedback",
  },
];

const custom_assistants_items = (
  isCurator: boolean,
  enableEnterprise: boolean
) => {
  const items = [
    {
      name: "Agents",
      icon: SvgOnyxOctagon,
      link: "/admin/assistants",
    },
  ];

  if (!isCurator) {
    items.push(
      {
        name: "Slack Bots",
        icon: SlackIconSkeleton,
        link: "/admin/bots",
      },
      {
        name: "Discord Bots",
        icon: SvgDiscordMono,
        link: "/admin/discord-bot",
      }
    );
  }

  items.push(
    {
      name: "MCP Actions",
      icon: SvgMcp,
      link: "/admin/actions/mcp",
    },
    {
      name: "OpenAPI Actions",
      icon: SvgActions,
      link: "/admin/actions/open-api",
    }
  );

  if (enableEnterprise) {
    items.push({
      name: "Standard Answers",
      icon: ClipboardIcon,
      link: "/admin/standard-answer",
    });
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
      items: custom_assistants_items(isCurator, enableEnterprise),
    },
    ...(isCurator && enableEnterprise
      ? [
          {
            name: "User Management",
            items: [
              {
                name: "Groups",
                icon: SvgUsers,
                link: "/admin/groups",
              },
            ],
          },
        ]
      : []),
    ...(!isCurator
      ? [
          {
            name: "Configuration",
            items: [
              {
                name: "Chat Preferences",
                icon: SvgBubbleText,
                link: "/admin/configuration/chat-preferences",
              },
              {
                name: "LLM",
                icon: SvgCpu,
                link: "/admin/configuration/llm",
              },
              {
                name: "Web Search",
                icon: SvgGlobe,
                link: "/admin/configuration/web-search",
              },
              {
                name: "Image Generation",
                icon: SvgImage,
                link: "/admin/configuration/image-generation",
              },
              {
                name: "Code Interpreter",
                icon: SvgTerminal,
                link: "/admin/configuration/code-interpreter",
              },
              ...(!enableCloud && vectorDbEnabled
                ? [
                    {
                      error: settings?.settings.needs_reindexing,
                      name: "Search Settings",
                      icon: SvgSearch,
                      link: "/admin/configuration/search",
                    },
                  ]
                : []),
              {
                name: "Document Processing",
                icon: SvgFileText,
                link: "/admin/configuration/document-processing",
              },
              ...(kgExposed
                ? [
                    {
                      name: "Knowledge Graph",
                      icon: BrainIcon,
                      link: "/admin/kg",
                    },
                  ]
                : []),
            ],
          },
          {
            name: "User Management",
            items: [
              {
                name: "Users",
                icon: SvgUser,
                link: "/admin/users",
              },
              ...(enableEnterprise
                ? [
                    {
                      name: "Groups",
                      icon: SvgUsers,
                      link: "/admin/groups",
                    },
                  ]
                : []),
              {
                name: "API Keys",
                icon: SvgKey,
                link: "/admin/api-key",
              },
              {
                name: "Token Rate Limits",
                icon: SvgShield,
                link: "/admin/token-rate-limits",
              },
            ],
          },
          ...(enableEnterprise
            ? [
                {
                  name: "Performance",
                  items: [
                    {
                      name: "Usage Statistics",
                      icon: SvgActivity,
                      link: "/admin/performance/usage",
                    },
                    ...(settings?.settings.query_history_type !== "disabled"
                      ? [
                          {
                            name: "Query History",
                            icon: SvgServer,
                            link: "/admin/performance/query-history",
                          },
                        ]
                      : []),
                    ...(!enableCloud && customAnalyticsEnabled
                      ? [
                          {
                            name: "Custom Analytics",
                            icon: SvgBarChart,
                            link: "/admin/performance/custom-analytics",
                          },
                        ]
                      : []),
                  ],
                },
              ]
            : []),
          {
            name: "Settings",
            items: [
              ...(enableEnterprise
                ? [
                    {
                      name: "Appearance & Theming",
                      icon: SvgPaintBrush,
                      link: "/admin/theme",
                    },
                  ]
                : []),
              // Always show billing/upgrade - community users need access to upgrade
              {
                name: hasSubscription ? "Plans & Billing" : "Upgrade Plan",
                icon: hasSubscription ? SvgWallet : SvgArrowUpCircle,
                link: "/admin/billing",
              },
              ...(settings?.settings.opensearch_indexing_enabled
                ? [
                    {
                      name: "Document Index Migration",
                      icon: SvgArrowExchange,
                      link: "/admin/document-index-migration",
                    },
                  ]
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
            leftIcon={({ className }) => (
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
                  transient={pathname.startsWith(link)}
                  leftIcon={({ className }) => (
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
