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
} from "@/components/icons/icons";
import { UserRole } from "@/lib/types";
import { FiActivity, FiBarChart2 } from "react-icons/fi";
import { UserDropdown } from "../UserDropdown";
import { User } from "@/lib/types";
import { usePathname } from "next/navigation";
import { SettingsContext } from "../settings/SettingsProvider";
import { useContext } from "react";
import { CustomTooltip } from "../tooltip/CustomTooltip";

export function ClientLayout({
  user,
  children,
  enableEnterprise,
}: {
  user: User | null;
  children: React.ReactNode;
  enableEnterprise: boolean;
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
    <div className="overflow-y-hidden">
      <div className="flex h-full">
        <div className="flex-none w-[250px] z-20 pt-4 pb-8 h-full border-r border-border miniscroll overflow-auto">
          <AdminSidebar
            collections={[
              {
                name: "Connectors",
                items: [
                  {
                    name: (
                      <div className="flex">
                        <NotebookIconSkeleton size={18} />
                        <div className="ml-1">Existing Connectors</div>
                      </div>
                    ),
                    link: "/admin/indexing/status",
                  },
                  {
                    name: (
                      <div className="flex">
                        <ConnectorIconSkeleton size={18} />
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
                        <DocumentSetIconSkeleton size={18} />
                        <div className="ml-1">Document Sets</div>
                      </div>
                    ),
                    link: "/admin/documents/sets",
                  },
                  {
                    name: (
                      <div className="flex">
                        <ZoomInIconSkeleton size={18} />
                        <div className="ml-1">Explorer</div>
                      </div>
                    ),
                    link: "/admin/documents/explorer",
                  },
                  {
                    name: (
                      <div className="flex">
                        <ThumbsUpIconSkeleton size={18} />
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
                        <AssistantsIconSkeleton className="my-auto" size={18} />
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
                              <SlackIconSkeleton />
                              <div className="ml-1">Slack Bots</div>
                            </div>
                          ),
                          link: "/admin/bot",
                        },
                        {
                          name: (
                            <div className="flex">
                              <ToolIconSkeleton size={18} />
                              <div className="ml-1">Tools</div>
                            </div>
                          ),
                          link: "/admin/tools",
                        },
                        {
                          name: (
                            <div className="flex">
                              <ClipboardIcon size={18} />
                              <div className="ml-1">Standard Answers</div>
                            </div>
                          ),
                          link: "/admin/standard-answer",
                        },
                        {
                          name: (
                            <div className="flex">
                              <ClosedBookIcon size={18} />
                              <div className="ml-1">Prompt Library</div>
                            </div>
                          ),
                          link: "/admin/prompt-library",
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
                              <GroupsIconSkeleton size={18} />
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
                              <CpuIconSkeleton size={18} />
                              <div className="ml-1">LLM</div>
                            </div>
                          ),
                          link: "/admin/configuration/llm",
                        },
                        {
                          error: settings?.settings.needs_reindexing,
                          name: (
                            <div className="flex">
                              <SearchIcon />
                              <div className="ml-1">Search Settings</div>
                            </div>
                          ),
                          link: "/admin/configuration/search",
                        },
                      ],
                    },
                    {
                      name: "User Management",
                      items: [
                        {
                          name: (
                            <div className="flex">
                              <UsersIconSkeleton size={18} />
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
                                    <GroupsIconSkeleton size={18} />
                                    <div className="ml-1">Groups</div>
                                  </div>
                                ),
                                link: "/admin/groups",
                              },
                              {
                                name: (
                                  <div className="flex">
                                    <KeyIconSkeleton size={18} />
                                    <div className="ml-1">API Keys</div>
                                  </div>
                                ),
                                link: "/admin/api-key",
                              },
                            ]
                          : []),
                        {
                          name: (
                            <div className="flex">
                              <ShieldIconSkeleton size={18} />
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
                                    <FiActivity size={18} />
                                    <div className="ml-1">Usage Statistics</div>
                                  </div>
                                ),
                                link: "/admin/performance/usage",
                              },
                              {
                                name: (
                                  <div className="flex">
                                    <DatabaseIconSkeleton size={18} />
                                    <div className="ml-1">Query History</div>
                                  </div>
                                ),
                                link: "/admin/performance/query-history",
                              },
                              {
                                name: (
                                  <div className="flex">
                                    <FiBarChart2 size={18} />
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
                              <SettingsIconSkeleton size={18} />
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
                                    <PaintingIconSkeleton size={18} />
                                    <div className="ml-1">Whitelabeling</div>
                                  </div>
                                ),
                                link: "/admin/whitelabeling",
                              },
                            ]
                          : []),
                      ],
                    },
                    {
                      name: "Customize Layout",
                      items: [
                        {
                          name: (
                            <div className="flex">
                              <CpuIconSkeleton size={18} />
                              <div className="ml-1">Welcome message</div>
                            </div>
                          ),
                          link: "/admin/eea_config/welcome_message",
                        },
                        {
                          name: (
                            <div className="flex">
                              <CpuIconSkeleton size={18} />
                              <div className="ml-1">Pages</div>
                            </div>
                          ),
                          link: "/admin/eea_config/pages",
                        },
                        // {
                        //   name: (
                        //     <div className="flex">
                        //       <CpuIconSkeleton size={18} />
                        //       <div className="ml-1">Footer</div>
                        //     </div>
                        //   ),
                        //   link: "/admin/eea_config/footer",
                        // },
                      ]
                    },
                  ]
                : []),
            ]}
          />
        </div>
        <div className="pb-8 relative h-full overflow-y-auto w-full">
          <div className="fixed bg-background left-0 gap-x-4 mb-8 px-4 py-2 w-full items-center flex justify-end">
            <UserDropdown user={user} />
          </div>
          <div className="pt-20 flex overflow-y-auto h-full px-4 md:px-12">
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}
