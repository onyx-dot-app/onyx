"use client";

import { usePathname } from "next/navigation";
import { useSettingsContext } from "@/components/settings/SettingsProvider";
import { CgArrowsExpandUpLeft } from "react-icons/cg";
import Text from "@/refresh-components/texts/Text";
import SidebarSection from "@/sections/sidebar/SidebarSection";
import Settings from "@/sections/sidebar/Settings/Settings";
import SidebarWrapper from "@/sections/sidebar/SidebarWrapper";
import { useIsKGExposed } from "@/app/admin/kg/utils";
import { useCustomAnalyticsEnabled } from "@/lib/hooks/useCustomAnalyticsEnabled";
import { useUser } from "@/components/user/UserProvider";
import { UserRole } from "@/lib/types";
import { MdOutlineCreditCard } from "react-icons/md";
import {
  ClipboardIcon,
  NotebookIconSkeleton,
  PaintingIconSkeleton,
  SlackIconSkeleton,
  BrainIcon,
} from "@/components/icons/icons";
import { CombinedSettings } from "@/app/admin/settings/interfaces";
import SidebarTab from "@/refresh-components/buttons/SidebarTab";
import SidebarBody from "@/sections/sidebar/SidebarBody";
import {
  SvgActions,
  SvgActivity,
  SvgBarChart,
  SvgCpu,
  SvgFileText,
  SvgFolder,
  SvgGlobe,
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
} from "@opal/icons";
import SvgMcp from "@opal/icons/mcp";
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
      name: "Assistants",
      icon: SvgOnyxOctagon,
      link: "/admin/assistants",
    },
  ];

  if (!isCurator) {
    items.push({
      name: "Slack Bots",
      icon: SlackIconSkeleton,
      link: "/admin/bots",
    });
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
              name: "Default Assistant",
              icon: SvgOnyxLogo,
              link: "/admin/configuration/default-assistant",
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
            ...(!enableCloud
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
            {
              name: "Workspace Settings",
              icon: SvgSettings,
              link: "/admin/settings",
            },
            ...(enableEnterprise
              ? [
                  {
                    name: "Appearance & Theming",
                    icon: SvgPaintBrush,
                    link: "/admin/theme",
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
  const { kgExposed } = useIsKGExposed();
  const pathname = usePathname();
  const { customAnalyticsEnabled } = useCustomAnalyticsEnabled();
  const { user } = useUser();
  const settings = useSettingsContext();

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
      <SidebarBody
        scrollKey="admin-sidebar"
        actionButton={
          <SidebarTab
            leftIcon={({ className }) => (
              <CgArrowsExpandUpLeft className={className} size={16} />
            )}
            href="/chat"
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
            <Settings />
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
