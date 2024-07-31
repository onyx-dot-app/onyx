import { Header } from "@/components/header/Header";
import { Footer } from "@/components/Footer";
import { AdminSidebar } from "@/components/admin/connectors/AdminSidebar";
import {
  NotebookIcon,
  UsersIcon,
  ThumbsUpIcon,
  BookmarkIcon,
  ZoomInIcon,
  RobotIcon,
  ConnectorIcon,
  GroupsIcon,
  DatabaseIcon,
  KeyIcon,
  ClipboardIcon,
  ChatIcon,
  SearchIcon,
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
  BookmarkIconSkeleton,
  ZoomInIconSkeleton,
  StarIconSkeleton,
  SlackIconSkeleton,
  DocumentSetIconSkeleton,
  EmbeddingIcon,
  EmbeddingIconSkeleton,
  BackIcon,
  AssistantsIcon,
  AssistantsIconSkeleton,
} from "@/components/icons/icons";
import { User } from "@/lib/types";
import {
  AuthTypeMetadata,
  getAuthTypeMetadataSS,
  getCurrentUserSS,
} from "@/lib/userSS";
import { SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED } from "@/lib/constants";
import { redirect } from "next/navigation";
import { fetchEEASettings } from "@/lib/eea/fetchEEASettings";
import {
  FiActivity,
  FiBarChart2,
  FiCpu,
  FiImage,
  FiPackage,
  FiSettings,
  FiShield,
  FiSlack,
  FiTool,
} from "react-icons/fi";
import { UserDropdown } from "../UserDropdown";
import { HealthCheckBanner } from "../health/healthcheck";
import { getSecondsUntilExpiration } from "@/lib/time";

export async function Layout({ children }: { children: React.ReactNode }) {
  const tasks = [
    getAuthTypeMetadataSS(),
    getCurrentUserSS(),
  ];

  // catch cases where the backend is completely unreachable here
  // without try / catch, will just raise an exception and the page
  // will not render
  let results: (User | Response | AuthTypeMetadata | null)[] = [null, null];
  try {
    results = await Promise.all(tasks);
  } catch (e) {
    console.log(`Some fetch failed for the main search page - ${e}`);
  }

  const authTypeMetadata = results[0] as AuthTypeMetadata | null;
  const user = results[1] as User | null;

  const config = await fetchEEASettings();
  
  const {
    footerHtml,
  } = config;
  

  
  const authDisabled = authTypeMetadata?.authType === "disabled";
  const requiresVerification = authTypeMetadata?.requiresVerification;
  if (!authDisabled) {
    if (!user) {
      return redirect("/auth/login");
    }
    if (user.role !== "admin") {
      return redirect("/");
    }
    if (!user.is_verified && requiresVerification) {
      return redirect("/auth/waiting-on-verification");
    }
  }

  const secondsUntilExpiration = getSecondsUntilExpiration(user);

  return (
    <div className="h-screen overflow-y-hidden">
      <HealthCheckBanner secondsUntilExpiration={secondsUntilExpiration} />
      <div className="flex h-full">
        <div className="w-64 z-20 bg-background-100 pt-3 pb-8 h-full border-r border-border miniscroll overflow-auto">
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
                  {
                    name: (
                      <div className="flex">
                        {/* <FiSlack size={18} /> */}
                        <SlackIconSkeleton />
                        <div className="ml-1">Slack Bots</div>
                      </div>
                    ),
                    link: "/admin/bot",
                  },
                  {
                    name: (
                      <div className="flex">
                        {/* <FiTool size={18} className="my-auto" /> */}
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
                ],
              },
              {
                name: "Model Configs",
                items: [
                  {
                    name: (
                      <div className="flex">
                        {/* <FiCpu size={18} /> */}
                        <CpuIconSkeleton size={18} />
                        <div className="ml-1">LLM</div>
                      </div>
                    ),
                    link: "/admin/models/llm",
                  },
                  {
                    name: (
                      <div className="flex">
                        <EmbeddingIconSkeleton />
                        <div className="ml-1">Embedding</div>
                      </div>
                    ),
                    link: "/admin/models/embedding",
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
                  ...(SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED
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
                        {/* <FiShield size={18} /> */}
                        <ShieldIconSkeleton size={18} />
                        <div className="ml-1">Token Rate Limits</div>
                      </div>
                    ),
                    link: "/admin/token-rate-limits",
                  },
                ],
              },
              ...(SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED
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
                  ...(SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED
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
                        <FiCpu size={18} />
                        <div className="ml-1">Welcome message</div>
                      </div>
                    ),
                    link: "/admin/eea_config/welcome_message",
                  },
                  {
                    name: (
                      <div className="flex">
                        <FiCpu size={18} />
                        <div className="ml-1">Pages</div>
                      </div>
                    ),
                    link: "/admin/eea_config/pages",
                  },
                  {
                    name: (
                      <div className="flex">
                        <FiCpu size={18} />
                        <div className="ml-1">Footer</div>
                      </div>
                    ),
                    link: "/admin/eea_config/footer",
                  },
                ],
              },
            ]}
          />
        </div>
        <div className="pb-8 relative h-full overflow-y-auto w-full">
          <div className="fixed bg-background left-0 gap-x-4 mb-8 px-4 py-2 w-full items-center flex justify-end">
            <UserDropdown user={user} />
          </div>
          <div className="pt-12 flex overflow-y-auto h-full px-4 md:px-12">
            {children}
          </div>
        </div>
      </div>
      <div className="absolute bottom-0 z-20 w-full">
        <Footer footerHtml={footerHtml}/>
      </div>
    </div>
  );
}
