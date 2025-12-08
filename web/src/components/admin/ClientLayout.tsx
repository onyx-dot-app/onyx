"use client";
import { useTranslation } from "@/hooks/useTranslation";
import k from "./../../i18n/keys";

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
  SettingsIconSkeleton,
  PaintingIconSkeleton,
  ZoomInIconSkeleton,
  KnowledgeMapIcon,
  DocumentSetIconSkeleton,
  AssistantsIconSkeleton,
  SearchIcon,
  DocumentIcon2,
} from "@/components/icons/icons";
import { UserRole } from "@/lib/types";
import { FiActivity, FiBarChart2, FiSettings } from "react-icons/fi";
import { UserDropdown } from "../UserDropdown";
import { User } from "@/lib/types";
import { usePathname } from "next/navigation";
import { SettingsContext } from "../settings/SettingsProvider";
import { useContext, useState } from "react";
import { MdOutlineCreditCard } from "react-icons/md";
import { UserSettingsModal } from "@/app/chat/modal/UserSettingsModal";
import { usePopup } from "./connectors/Popup";
import { useChatContext } from "../context/ChatContext";
import { ApplicationStatus } from "@/app/admin/settings/interfaces";
import Link from "next/link";
import { Button } from "../ui/button";

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
  const { t } = useTranslation();
  const isCurator =
    user?.role === UserRole.CURATOR || user?.role === UserRole.GLOBAL_CURATOR;
  const pathname = usePathname();
  const settings = useContext(SettingsContext);
  const [userSettingsOpen, setUserSettingsOpen] = useState(false);
  const toggleUserSettings = () => {
    setUserSettingsOpen(!userSettingsOpen);
  };
  const { llmProviders } = useChatContext();
  const { popup, setPopup } = usePopup();

  const isLangflowEditorEnable =
    process.env.NEXT_PUBLIC_ENABLE_LANGFLOW_EDITOR === "true";

  const isLangfuseEditorEnable =
    process.env.NEXT_PUBLIC_ENABLE_LANGFUSE_EDITOR === "true";

  console.log(
    "ENV",
    process.env.NEXT_PUBLIC_ENABLE_LANGFLOW_EDITOR,
    process.env.NEXT_PUBLIC_ENABLE_LANGFUSE_EDITOR
  );
  if (
    (pathname && pathname.startsWith("/admin/connectors")) ||
    (pathname && pathname.startsWith("/admin/embeddings"))
  ) {
    return <>{children}</>;
  }

  return (
    <div className="h-screen overflow-y-hidden">
      {popup}
      <div className="flex h-full">
        {userSettingsOpen && (
          <UserSettingsModal
            llmProviders={llmProviders}
            setPopup={setPopup}
            onClose={() => setUserSettingsOpen(false)}
            defaultModel={user?.preferences?.default_model!}
          />
        )}

        {settings?.settings.application_status ===
          ApplicationStatus.PAYMENT_REMINDER && (
          <div className="fixed top-2 left-1/2 transform -translate-x-1/2 bg-amber-400 dark:bg-amber-500 text-gray-900 dark:text-gray-100 p-4 rounded-lg shadow-lg z-50 max-w-md text-center">
            <strong className="font-bold">{t(k.WARNING2)}</strong>{" "}
            {t(k.YOUR_TRIAL_ENDS_IN)}
            <div className="mt-2">
              <Link href="/admin/billing">
                <Button
                  variant="default"
                  className="bg-amber-600 hover:bg-amber-700 text-white"
                >
                  {t(k.UPDATE_BILLING_INFORMATION)}
                </Button>
              </Link>
            </div>
          </div>
        )}

        <div className="default-scrollbar flex-none text-text-settings-sidebar bg-background-sidebar dark:bg-[#000] w-[250px] overflow-x-hidden z-20 pt-2 pb-8 h-full border-r border-border dark:border-none miniscroll overflow-auto">
          <AdminSidebar
            collections={[
              {
                name: t(k.CONNECTORS),
                items: [
                  {
                    name: (
                      <div className="flex">
                        <NotebookIconSkeleton
                          className="text-text-700"
                          size={18}
                        />

                        <div className="ml-1">{t(k.EXISTING_CONNECTORS)}</div>
                      </div>
                    ),

                    link: t(k.ADMIN_INDEXING_STATUS),
                  },
                  {
                    name: (
                      <div className="flex">
                        <ConnectorIconSkeleton
                          className="text-text-700"
                          size={18}
                        />

                        <div className="ml-1.5">{t(k.ADD_CONNECTOR)}</div>
                      </div>
                    ),

                    link: t(k.ADMIN_ADD_CONNECTOR),
                  },
                ],
              },
              {
                name: t(k.DOCUMENT_MANAGEMENT),
                items: [
                  {
                    name: (
                      <div className="flex">
                        <DocumentSetIconSkeleton
                          className="text-text-700"
                          size={18}
                        />

                        <div className="ml-1">{t(k.DOCUMENT_SETS)}</div>
                      </div>
                    ),

                    link: t(k.ADMIN_DOCUMENTS_SETS1),
                  },
                  {
                    name: (
                      <div className="flex">
                        <ZoomInIconSkeleton
                          className="text-text-700"
                          size={18}
                        />

                        <div className="ml-1">{t(k.EXPLORER)}</div>
                      </div>
                    ),

                    link: t(k.ADMIN_DOCUMENTS_EXPLORER),
                  },
                  {
                    name: (
                      <div className="flex">
                        <ThumbsUpIconSkeleton
                          className="text-text-700"
                          size={18}
                        />

                        <div className="ml-1">{t(k.FEEDBACK)}</div>
                      </div>
                    ),

                    link: t(k.ADMIN_DOCUMENTS_FEEDBACK),
                  },
                  {
                    name: (
                      <div className="flex">
                        <KnowledgeMapIcon className="text-text-700" size={18} />

                        <div className="ml-1">{t(k.KNOWLEDGE_MAP)}</div>
                      </div>
                    ),

                    link: "/admin/documents/knowledge_maps",
                  },
                ],
              },
              {
                name: t(k.CUSTOM_ASSISTANTS),
                items: [
                  {
                    name: (
                      <div className="flex">
                        <AssistantsIconSkeleton
                          className="text-text-700"
                          size={18}
                        />

                        <div className="ml-1">{t(k.ASSISTANTS1)}</div>
                      </div>
                    ),

                    link: t(k.ADMIN_ASSISTANTS),
                  },
                  ...(!isCurator
                    ? [
                        // {
                        //   name: (
                        //     <div className="flex">
                        //       <SlackIconSkeleton className="text-text-700" />
                        //       <div className="ml-1">{t(k.SLACK_BOTS)}</div>
                        //     </div>
                        //   ),

                        //   link: t(k.ADMIN_BOTS1),
                        // },
                        {
                          name: (
                            <div className="flex">
                              <ToolIconSkeleton
                                className="text-text-700"
                                size={18}
                              />

                              <div className="ml-1">{t(k.ACTIONS)}</div>
                            </div>
                          ),

                          link: t(k.ADMIN_ACTIONS),
                        },
                      ]
                    : []),
                  ...(enableEnterprise
                    ? [
                        {
                          name: (
                            <div className="flex">
                              <ClipboardIcon
                                className="text-text-700"
                                size={18}
                              />

                              <div className="ml-1">
                                {t(k.STANDARD_ANSWERS)}
                              </div>
                            </div>
                          ),

                          link: t(k.ADMIN_STANDARD_ANSWER),
                        },
                      ]
                    : []),
                  {
                    name: (
                      <div className="flex">
                        <ShieldIconSkeleton className="text-text-700" />
                        <div className="ml-1">{t(k.VALIDATORS)}</div>
                      </div>
                    ),

                    link: "/admin/guardrails",
                  },
                ],
              },
              ...(isCurator
                ? [
                    {
                      name: t(k.USER_MANAGEMENT),
                      items: [
                        {
                          name: (
                            <div className="flex">
                              <GroupsIconSkeleton
                                className="text-text-700"
                                size={18}
                              />

                              <div className="ml-1">{t(k.GROUPS)}</div>
                            </div>
                          ),

                          link: t(k.ADMIN_GROUPS1),
                        },
                      ],
                    },
                  ]
                : []),
              ...(!isCurator
                ? [
                    {
                      name: t(k.CONFIGURATION),
                      items: [
                        {
                          name: (
                            <div className="flex">
                              <CpuIconSkeleton
                                className="text-text-700"
                                size={18}
                              />

                              <div className="ml-1">{t(k.LLM)}</div>
                            </div>
                          ),

                          link: t(k.ADMIN_CONFIGURATION_LLM),
                        },
                        {
                          error: settings?.settings.needs_reindexing,
                          name: (
                            <div className="flex">
                              <SearchIcon className="text-text-700" />
                              <div className="ml-1">{t(k.SEARCH_SETTINGS)}</div>
                            </div>
                          ),

                          link: t(k.ADMIN_CONFIGURATION_SEARCH),
                        },
                        {
                          name: (
                            <div className="flex">
                              <DocumentIcon2 className="text-text-700" />
                              <div className="ml-1">
                                {t(k.DOCUMENT_PROCESSING)}
                              </div>
                            </div>
                          ),

                          link: t(k.ADMIN_CONFIGURATION_DOCUMENT),
                        },
                      ],
                    },
                    {
                      name: t(k.USER_MANAGEMENT),
                      items: [
                        {
                          name: (
                            <div className="flex">
                              <UsersIconSkeleton
                                className="text-text-700"
                                size={18}
                              />

                              <div className="ml-1">{t(k.USERS)}</div>
                            </div>
                          ),

                          link: t(k.ADMIN_USERS),
                        },
                        ...(enableEnterprise
                          ? [
                              {
                                name: (
                                  <div className="flex">
                                    <GroupsIconSkeleton
                                      className="text-text-700"
                                      size={18}
                                    />

                                    <div className="ml-1">{t(k.GROUPS)}</div>
                                  </div>
                                ),

                                link: t(k.ADMIN_GROUPS1),
                              },
                            ]
                          : []),
                        {
                          name: (
                            <div className="flex">
                              <KeyIconSkeleton
                                className="text-text-700"
                                size={18}
                              />

                              <div className="ml-1">{t(k.API_KEYS)}</div>
                            </div>
                          ),

                          link: t(k.ADMIN_API_KEY),
                        },
                        {
                          name: (
                            <div className="flex">
                              <ShieldIconSkeleton
                                className="text-text-700"
                                size={18}
                              />

                              <div className="ml-1">
                                {t(k.TOKEN_RATE_LIMITS)}
                              </div>
                            </div>
                          ),

                          link: t(k.ADMIN_TOKEN_RATE_LIMITS),
                        },
                      ],
                    },
                    ...(enableEnterprise
                      ? [
                          {
                            name: t(k.PERFORMANCE),
                            items: [
                              {
                                name: (
                                  <div className="flex">
                                    <FiActivity
                                      className="text-text-700"
                                      size={18}
                                    />

                                    <div className="ml-1">
                                      {t(k.USAGE_STATISTICS)}
                                    </div>
                                  </div>
                                ),

                                link: t(k.ADMIN_PERFORMANCE_USAGE),
                              },
                              {
                                name: (
                                  <div className="flex">
                                    <FiBarChart2
                                      className="text-text-700"
                                      size={18}
                                    />

                                    <div className="ml-1">
                                      {t(k.CUSTOM_ANALYTICS)}
                                    </div>
                                  </div>
                                ),

                                link: t(k.ADMIN_PERFORMANCE_CUSTOM_ANAL),
                              },
                            ],
                          },
                        ]
                      : []),
                    {
                      name: t(k.SETTINGS),
                      items: [
                        {
                          name: (
                            <div className="flex">
                              <SettingsIconSkeleton
                                className="text-text-700"
                                size={18}
                              />

                              <div className="ml-1">
                                {t(k.WORKSPACE_SETTINGS)}
                              </div>
                            </div>
                          ),

                          link: t(k.ADMIN_SETTINGS),
                        },
                        ...(enableEnterprise
                          ? [
                              {
                                name: (
                                  <div className="flex">
                                    <PaintingIconSkeleton
                                      className="text-text-700"
                                      size={18}
                                    />

                                    <div className="ml-1">
                                      {t(k.WHITELABELING)}
                                    </div>
                                  </div>
                                ),

                                link: t(k.ADMIN_WHITELABELING),
                              },
                            ]
                          : []),
                        ...(enableCloud
                          ? [
                              {
                                name: (
                                  <div className="flex">
                                    <MdOutlineCreditCard
                                      className="text-text-700"
                                      size={18}
                                    />

                                    <div className="ml-1">{t(k.BILLING)}</div>
                                  </div>
                                ),

                                link: t(k.ADMIN_BILLING),
                              },
                            ]
                          : []),
                      ],
                    },
                    {
                      name: t(k.USER_TOOLS),
                      items: [
                        {
                          name: (
                            <div className="flex">
                              <FiSettings size={18} />
                              <div className="ml-1">{t(k.LANGFLOW_EDITOR)}</div>
                            </div>
                          ),
                          link: "/admin/usertools/langflow",
                        },
                        {
                          name: (
                            <div className="flex">
                              <FiSettings size={18} />
                              <div className="ml-1">
                                {t(k.LANGFUSE_MONITORING)}
                              </div>
                            </div>
                          ),
                          link: "/admin/usertools/langfuse",
                        },
                      ],
                    },
                  ]
                : []),
            ]}
          />
        </div>
        <div className="relative h-full overflow-y-hidden w-full">
          <div className="fixed left-0 gap-x-4 px-4 top-4 h-8 px-0 mb-auto w-full items-start flex justify-end">
            <UserDropdown toggleUserSettings={toggleUserSettings} />
          </div>
          <div className="pt-20 flex w-full overflow-y-auto overflow-x-hidden h-full px-4 md:px-12">
            {children}
          </div>
        </div>
      </div>
    </div>
  );

  // Is there a clean way to add this to some piece of text where we need to enbale for copy-paste in a react app?
}
