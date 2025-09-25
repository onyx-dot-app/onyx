"use client";

import { AdminSidebar } from "@/sections/sidebar/AdminSidebar";
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
import { UserRole } from "@/lib/types";
import { FiActivity, FiBarChart2 } from "react-icons/fi";
import { User } from "@/lib/types";
import { usePathname } from "next/navigation";
import { useSettingsContext } from "@/components/settings/SettingsProvider";
import { MdOutlineCreditCard } from "react-icons/md";
import {
  ApplicationStatus,
  CombinedSettings,
} from "@/app/admin/settings/interfaces";
import Link from "next/link";
import { Button } from "../ui/button";
import { useIsKGExposed } from "@/app/admin/kg/utils";
import { useCustomAnalyticsEnabled } from "@/lib/hooks/useCustomAnalyticsEnabled";

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
            {
              error: settings?.settings.needs_reindexing,
              name: "Search Settings",
              icon: SearchIcon,
              link: "/admin/configuration/search",
            },
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

export function ClientLayout({
  user,
  children,
  enableEnterprise,
  enableCloud,
}: {
  user: User | null;
  children: React.ReactNode;
  enableEnterprise: boolean;
  enableCloud: boolean;
}) {
  const { kgExposed, isLoading } = useIsKGExposed();
  const { customAnalyticsEnabled } = useCustomAnalyticsEnabled();

  const isCurator =
    user?.role === UserRole.CURATOR || user?.role === UserRole.GLOBAL_CURATOR;

  const pathname = usePathname();
  const settings = useSettingsContext();

  if (isLoading) {
    return <></>;
  }

  if (
    (pathname && pathname.startsWith("/admin/connectors")) ||
    (pathname && pathname.startsWith("/admin/embeddings"))
  ) {
    return <>{children}</>;
  }

  return (
    <div className="h-screen w-screen flex overflow-y-hidden">
      {settings?.settings.application_status ===
        ApplicationStatus.PAYMENT_REMINDER && (
        <div className="fixed top-2 left-1/2 transform -translate-x-1/2 bg-amber-400 dark:bg-amber-500 text-gray-900 dark:text-gray-100 p-4 rounded-lg shadow-lg z-50 max-w-md text-center">
          <strong className="font-bold">Warning:</strong> Your trial ends in
          less than 5 days and no payment method has been added.
          <div className="mt-2">
            <Link href="/admin/billing">
              <Button
                variant="default"
                className="bg-amber-600 hover:bg-amber-700 text-white"
              >
                Update Billing Information
              </Button>
            </Link>
          </div>
        </div>
      )}

      <AdminSidebar
        collections={collections(
          isCurator,
          enableCloud,
          enableEnterprise,
          settings,
          kgExposed,
          customAnalyticsEnabled
        )}
      />

      <div className="overflow-y-scroll w-full flex pt-10 pb-4 px-4 md:px-12">
        {children}
      </div>
    </div>
  );
}
