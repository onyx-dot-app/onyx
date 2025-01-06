"use client";

import { AdminSidebar } from "@/components/admin/connectors/AdminSidebar";
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
  ClosedBookIcon,
  SearchIcon,
  DocumentIcon2,
} from "@/components/icons/icons";
import { UserRole } from "@/lib/types";
import { FiActivity, FiBarChart2 } from "react-icons/fi";
import { UserDropdown } from "../UserDropdown";
import { User } from "@/lib/types";
import { usePathname } from "next/navigation";
import { SettingsContext } from "../settings/SettingsProvider";
import { useContext } from "react";
import { MdOutlineCreditCard } from "react-icons/md";

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
  const isCurator =
    user?.role === UserRole.CURATOR || user?.role === UserRole.GLOBAL_CURATOR;
  const pathname = usePathname();
  const settings = useContext(SettingsContext);

  if (
    pathname.startsWith("/admin/connectors") ||
    pathname.startsWith("/admin/embeddings")
  ) {
    return <>{children}</>;
  }

  return (
    <div className="h-screen overflow-y-hidden">
      <div className="flex h-full">
        <div className="flex-none text-text-settings-sidebar bg-background-sidebar w-[250px] overflow-x-hidden z-20 pt-2 pb-8 h-full border-r border-border miniscroll overflow-auto">
          <AdminSidebar
            collections={[
              {
                name: "Connectors",
                items: [
                  {
                    name: (
                      <div className="flex">
                        <NotebookIconSkeleton
                          className="text-icon-settings-sidebar"
                          size={18}
                        />
                        <div className="ml-1">Existing Connectors</div>
                      </div>
                    ),
                    link: "/admin/indexing/status",
                  },
                  {
                    name: (
                      <div className="flex">
                        <ConnectorIconSkeleton
                          className="text-icon-settings-sidebar"
                          size={18}
                        />
                        <div className="ml-1.5">Add Connector</div>
                      </div>
                    ),
                    link: "/admin/add-connector",
                  },
                ],
              },
              {
                name: "Document Management",
                items: [
                  {
                    name: (
                      <div className="flex">
                        <DocumentSetIconSkeleton
                          className="text-icon-settings-sidebar"
                          size={18}
                        />
                        <div className="ml-1">Document Sets</div>
                      </div>
                    ),
                    link: "/admin/documents/sets",
                  },
                  {
                    name: (
                      <div className="flex">
                        <ZoomInIconSkeleton
                          className="text-icon-settings-sidebar"
                          size={18}
                        />
                        <div className="ml-1">Explorer</div>
                      </div>
                    ),
                    link: "/admin/documents/explorer",
                  },
                  {
                    name: (
                      <div className="flex">
                        <ThumbsUpIconSkeleton
                          className="text-icon-settings-sidebar"
                          size={18}
                        />
                        <div className="ml-1">Feedback</div>
                      </div>
                    ),
                    link: "/admin/documents/feedback",
                  },
                ],
              },
              {
                name: "Custom Assistants",
                items: [
                  {
                    name: (
                      <div className="flex">
                        <AssistantsIconSkeleton
                          className="text-icon-settings-sidebar"
                          size={18}
                        />
                        <div className="ml-1">Assistants</div>
                      </div>
                    ),
                    link: "/admin/assistants",
                  },
                  ...(!isCurator
                    ? [
                        {
                          name: (
                            <div className="flex">
                              <SlackIconSkeleton className="text-icon-settings-sidebar" />
                              <div className="ml-1">Slack Bots</div>
                            </div>
                          ),
                          link: "/admin/bots",
                        },
                        {
                          name: (
                            <div className="flex">
                              <ToolIconSkeleton
                                className="text-icon-settings-sidebar"
                                size={18}
                              />
                              <div className="ml-1">Tools</div>
                            </div>
                          ),
                          link: "/admin/tools",
                        },
                      ]
                    : []),
                  ...(enableEnterprise
                    ? [
                        {
                          name: (
                            <div className="flex">
                              <ClipboardIcon
                                className="text-icon-settings-sidebar"
                                size={18}
                              />
                              <div className="ml-1">Standard Answers</div>
                            </div>
                          ),
                          link: "/admin/standard-answer",
                        },
                      ]
                    : []),
                ],
              },
              ...(isCurator
                ? [
                    {
                      name: "User Management",
                      items: [
                        {
                          name: (
                            <div className="flex">
                              <GroupsIconSkeleton
                                className="text-icon-settings-sidebar"
                                size={18}
                              />
                              <div className="ml-1">Groups</div>
                            </div>
                          ),
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
                          name: (
                            <div className="flex">
                              <CpuIconSkeleton
                                className="text-icon-settings-sidebar"
                                size={18}
                              />
                              <div className="ml-1">LLM</div>
                            </div>
                          ),
                          link: "/admin/configuration/llm",
                        },
                        {
                          error: settings?.settings.needs_reindexing,
                          name: (
                            <div className="flex">
                              <SearchIcon className="text-icon-settings-sidebar" />
                              <div className="ml-1">Search Settings</div>
                            </div>
                          ),
                          link: "/admin/configuration/search",
                        },
                        {
                          name: (
                            <div className="flex">
                              <DocumentIcon2 className="text-icon-settings-sidebar" />
                              <div className="ml-1">Document Processing</div>
                            </div>
                          ),
                          link: "/admin/configuration/document-processing",
                        },
                      ],
                    },
                    {
                      name: "User Management",
                      items: [
                        {
                          name: (
                            <div className="flex">
                              <UsersIconSkeleton
                                className="text-icon-settings-sidebar"
                                size={18}
                              />
                              <div className="ml-1">Users</div>
                            </div>
                          ),
                          link: "/admin/users",
                        },
                        ...(enableEnterprise
                          ? [
                              {
                                name: (
                                  <div className="flex">
                                    <GroupsIconSkeleton
                                      className="text-icon-settings-sidebar"
                                      size={18}
                                    />
                                    <div className="ml-1">Groups</div>
                                  </div>
                                ),
                                link: "/admin/groups",
                              },
                            ]
                          : []),
                        {
                          name: (
                            <div className="flex">
                              <KeyIconSkeleton
                                className="text-icon-settings-sidebar"
                                size={18}
                              />
                              <div className="ml-1">API Keys</div>
                            </div>
                          ),
                          link: "/admin/api-key",
                        },
                        {
                          name: (
                            <div className="flex">
                              <ShieldIconSkeleton
                                className="text-icon-settings-sidebar"
                                size={18}
                              />
                              <div className="ml-1">Token Rate Limits</div>
                            </div>
                          ),
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
                                name: (
                                  <div className="flex">
                                    <FiActivity
                                      className="text-icon-settings-sidebar"
                                      size={18}
                                    />
                                    <div className="ml-1">Usage Statistics</div>
                                  </div>
                                ),
                                link: "/admin/performance/usage",
                              },
                              {
                                name: (
                                  <div className="flex">
                                    <DatabaseIconSkeleton
                                      className="text-icon-settings-sidebar"
                                      size={18}
                                    />
                                    <div className="ml-1">Query History</div>
                                  </div>
                                ),
                                link: "/admin/performance/query-history",
                              },
                              {
                                name: (
                                  <div className="flex">
                                    <FiBarChart2
                                      className="text-icon-settings-sidebar"
                                      size={18}
                                    />
                                    <div className="ml-1">Custom Analytics</div>
                                  </div>
                                ),
                                link: "/admin/performance/custom-analytics",
                              },
                            ],
                          },
                        ]
                      : []),
                    {
                      name: "Settings",
                      items: [
                        {
                          name: (
                            <div className="flex">
                              <SettingsIconSkeleton
                                className="text-icon-settings-sidebar"
                                size={18}
                              />
                              <div className="ml-1">Workspace Settings</div>
                            </div>
                          ),
                          link: "/admin/settings",
                        },
                        ...(enableEnterprise
                          ? [
                              {
                                name: (
                                  <div className="flex">
                                    <PaintingIconSkeleton
                                      className="text-icon-settings-sidebar"
                                      size={18}
                                    />
                                    <div className="ml-1">Whitelabeling</div>
                                  </div>
                                ),
                                link: "/admin/whitelabeling",
                              },
                            ]
                          : []),
                        ...(enableCloud
                          ? [
                              {
                                name: (
                                  <div className="flex">
                                    <MdOutlineCreditCard
                                      className="text-icon-settings-sidebar"
                                      size={18}
                                    />
                                    <div className="ml-1">Billing</div>
                                  </div>
                                ),
                                link: "/admin/billing",
                              },
                            ]
                          : []),
                      ],
                    },
                  ]
                : []),
            ]}
          />
        </div>
        <div className="pb-8 relative h-full overflow-y-auto w-full">
          <div className="fixed left-0 gap-x-4 px-2 top-2 h-8 px-0 mb-auto w-full items-start flex justify-end">
            <UserDropdown />
          </div>
          <div className="pt-20 flex overflow-y-auto overflow-x-hidden h-full px-4 md:px-12">
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}
