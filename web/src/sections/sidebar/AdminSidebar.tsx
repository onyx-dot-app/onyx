"use client";

import React, { useContext } from "react";
import { usePathname } from "next/navigation";
import {
  SettingsContext,
  useSettingsContext,
} from "@/components/settings/SettingsProvider";
import { CgArrowsExpandUpLeft } from "react-icons/cg";
import Text from "@/refresh-components/texts/Text";
import { SidebarSection } from "@/sections/sidebar/SidebarSection";
import Settings from "@/sections/sidebar/Settings";
import SidebarWrapper from "@/sections/sidebar/SidebarWrapper";
import { useIsKGExposed } from "@/app/admin/kg/utils";
import { useCustomAnalyticsEnabled } from "@/lib/hooks/useCustomAnalyticsEnabled";
import { useUser } from "@/components/user/UserProvider";
import { UserRole } from "@/lib/types";
import { MdOutlineCreditCard } from "react-icons/md";
import {
  ClipboardIcon,
  NotebookIconSkeleton,
  ConnectorIconSkeleton,
  ThumbsUpIconSkeleton,
  ToolIconSkeleton,
  CpuIconSkeleton,
  UsersIconSkeleton,
  GroupsIconSkeleton,
  KeyIconSkeleton,
  ShieldIconSkeleton,
  DatabaseIconSkeleton,
  SettingsIconSkeleton,
  PaintingIconSkeleton,
  ZoomInIconSkeleton,
  SlackIconSkeleton,
  DocumentSetIconSkeleton,
  AssistantsIconSkeleton,
  SearchIcon,
  DocumentIcon2,
  BrainIcon,
  OnyxSparkleIcon,
} from "@/components/icons/icons";
import { CombinedSettings } from "@/app/admin/settings/interfaces";
import { FiActivity, FiBarChart2 } from "react-icons/fi";
import SidebarTab from "@/refresh-components/buttons/SidebarTab";
import VerticalShadowScroller from "@/refresh-components/VerticalShadowScroller";

const connectors_items = () => [
  {
    name: "Existing Connectors",
    icon: NotebookIconSkeleton,
    link: "/admin/indexing/status",
  },
  {
    name: "Add Connector",
    icon: ConnectorIconSkeleton,
    link: "/admin/add-connector",
  },
];

const document_management_items = () => [
  {
    name: "Document Sets",
    icon: DocumentSetIconSkeleton,
    link: "/admin/documents/sets",
  },
  {
    name: "Explorer",
    icon: ZoomInIconSkeleton,
    link: "/admin/documents/explorer",
  },
  {
    name: "Feedback",
    icon: ThumbsUpIconSkeleton,
    link: "/admin/documents/feedback",
  },
];

const custom_assistants_items = (
  isCurator: boolean,
  enableEnterprise: boolean
) => {
  const items = [
    {
      name: "Assistants",
      icon: AssistantsIconSkeleton,
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
        name: "Actions",
        icon: ToolIconSkeleton,
        link: "/admin/actions",
      }
    );
  } else {
    items.push({
      name: "Actions",
      icon: ToolIconSkeleton,
      link: "/admin/actions",
    });
  }

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
  customAnalyticsEnabled: boolean
) => [
  {
    name: "Connectors",
    items: connectors_items(),
  },
  {
    name: "Document Management",
    items: document_management_items(),
  },
  {
    name: "Custom Assistants",
    items: custom_assistants_items(isCurator, enableEnterprise),
  },
  ...(isCurator
    ? [
        {
          name: "User Management",
          items: [
            {
              name: "Groups",
              icon: GroupsIconSkeleton,
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
              name: "Default Assistant",
              icon: OnyxSparkleIcon,
              link: "/admin/configuration/default-assistant",
            },
            {
              name: "LLM",
              icon: CpuIconSkeleton,
              link: "/admin/configuration/llm",
            },
            ...(!enableCloud
              ? [
                  {
                    error: settings?.settings.needs_reindexing,
                    name: "Search Settings",
                    icon: SearchIcon,
                    link: "/admin/configuration/search",
                  },
                ]
              : []),
            {
              name: "Document Processing",
              icon: DocumentIcon2,
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
              icon: UsersIconSkeleton,
              link: "/admin/users",
            },
            ...(enableEnterprise
              ? [
                  {
                    name: "Groups",
                    icon: GroupsIconSkeleton,
                    link: "/admin/groups",
                  },
                ]
              : []),
            {
              name: "API Keys",
              icon: KeyIconSkeleton,
              link: "/admin/api-key",
            },
            {
              name: "Token Rate Limits",
              icon: ShieldIconSkeleton,
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
                    icon: FiActivity,
                    link: "/admin/performance/usage",
                  },
                  ...(settings?.settings.query_history_type !== "disabled"
                    ? [
                        {
                          name: "Query History",
                          icon: DatabaseIconSkeleton,
                          link: "/admin/performance/query-history",
                        },
                      ]
                    : []),
                  ...(!enableCloud && customAnalyticsEnabled
                    ? [
                        {
                          name: "Custom Analytics",
                          icon: FiBarChart2,
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
            {
              name: "Workspace Settings",
              icon: SettingsIconSkeleton,
              link: "/admin/settings",
            },
            ...(enableEnterprise
              ? [
                  {
                    name: "Whitelabeling",
                    icon: PaintingIconSkeleton,
                    link: "/admin/whitelabeling",
                  },
                ]
              : []),
            ...(enableCloud
              ? [
                  {
                    name: "Billing",
                    icon: MdOutlineCreditCard,
                    link: "/admin/billing",
                  },
                ]
              : []),
          ],
        },
      ]
    : []),
];

interface AdminSidebarProps {
  // These props are passed down from a server component (Layout.tsx) that
  // determines feature availability server-side. We don't calculate these
  // directly in this client component to avoid:
  // 1. Unnecessary API calls on the client-side
  // 2. Security concerns - preventing end-users from tampering with
  //    feature flags by making direct API calls
  // 3. Performance - avoiding refetches when the data is already available
  enableCloudSS: boolean;
  enableEnterpriseSS: boolean;
}

export default function AdminSidebar({
  enableCloudSS,
  enableEnterpriseSS,
}: AdminSidebarProps) {
  const { kgExposed, isLoading: isKgExposedLoading } = useIsKGExposed();
  const combinedSettings = useContext(SettingsContext);
  const pathname = usePathname() ?? "";
  const { customAnalyticsEnabled } = useCustomAnalyticsEnabled();
  const { user } = useUser();
  const settings = useSettingsContext();

  if (!combinedSettings || isKgExposedLoading) {
    return null;
  }

  const isCurator =
    user?.role === UserRole.CURATOR || user?.role === UserRole.GLOBAL_CURATOR;

  const items = collections(
    isCurator,
    enableCloudSS,
    enableEnterpriseSS,
    settings,
    kgExposed,
    customAnalyticsEnabled
  );

  return (
    <SidebarWrapper>
      <div className="px-spacing-interline">
        <SidebarTab
          leftIcon={({ className }) => (
            <CgArrowsExpandUpLeft className={className} size={16} />
          )}
          href="/chat"
        >
          Exit Admin
        </SidebarTab>
      </div>

      {/* This is the main scrollable body. It should have top + bottom shadows on overflow */}
      <VerticalShadowScroller className="flex px-spacing-interline gap-padding-content">
        {items.map((collection, index) => (
          <SidebarSection key={index} title={collection.name}>
            <div className="flex flex-col w-full">
              {collection.items.map(({ link, icon: Icon, name }, index) => (
                <SidebarTab
                  key={index}
                  href={link}
                  active={pathname.startsWith(link)}
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
      </VerticalShadowScroller>

      <div className="flex flex-col px-spacing-interline gap-spacing-interline">
        {combinedSettings.webVersion && (
          <Text text02 secondaryBody className="px-spacing-interline">
            {`Onyx version: ${combinedSettings.webVersion}`}
          </Text>
        )}
        <Settings removeAdminPanelLink />
      </div>
    </SidebarWrapper>
  );
}
