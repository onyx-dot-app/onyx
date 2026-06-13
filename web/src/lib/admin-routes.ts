import { IconFunctionComponent } from "@opal/types";
import {
  SvgActions,
  SvgActivity,
  SvgAudio,
  SvgShareWebhook,
  SvgBarChart,
  SvgBookOpen,
  SvgBubbleText,
  SvgClipboard,
  SvgCpu,
  SvgDownload,
  SvgEmpty,
  SvgFileText,
  SvgFiles,
  SvgGlobe,
  SvgHistory,
  SvgImage,
  SvgMcp,
  SvgPaintBrush,
  SvgProgressBars,
  SvgSearchMenu,
  SvgShield,
  SvgTerminal,
  SvgThumbsUp,
  SvgUploadCloud,
  SvgUser,
  SvgUserKey,
  SvgUserSync,
  SvgUsers,
  SvgWallet,
  SvgZoomIn,
  SvgDiscord,
  SvgSlack,
  SvgSparkle,
} from "@opal/icons";

export interface AdminRouteEntry {
  path: string;
  icon: IconFunctionComponent;
  title: string;
  sidebarLabel: string;
}

/**
 * Single source of truth for every admin route: path, icon, page-header
 * title, and sidebar label.
 */
export const ADMIN_ROUTES = {
  INDEXING_STATUS: {
    path: "/admin/indexing/status",
    icon: SvgBookOpen,
    title: "现有连接器",
    sidebarLabel: "现有连接器",
  },
  ADD_CONNECTOR: {
    path: "/admin/add-connector",
    icon: SvgUploadCloud,
    title: "添加连接器",
    sidebarLabel: "添加连接器",
  },
  DOCUMENT_SETS: {
    path: "/admin/documents/sets",
    icon: SvgFiles,
    title: "文档集",
    sidebarLabel: "文档集",
  },
  DOCUMENT_EXPLORER: {
    path: "/admin/documents/explorer",
    icon: SvgZoomIn,
    title: "文档浏览器",
    sidebarLabel: "浏览器",
  },
  DOCUMENT_FEEDBACK: {
    path: "/admin/documents/feedback",
    icon: SvgThumbsUp,
    title: "文档反馈",
    sidebarLabel: "反馈",
  },
  AGENTS: {
    path: "/admin/agents",
    icon: SvgSparkle,
    title: "智能体",
    sidebarLabel: "智能体",
  },
  SLACK_BOTS: {
    path: "/admin/bots",
    icon: SvgSlack,
    title: "Slack 集成",
    sidebarLabel: "Slack 集成",
  },
  DISCORD_BOTS: {
    path: "/admin/discord-bot",
    icon: SvgDiscord,
    title: "Discord 集成",
    sidebarLabel: "Discord 集成",
  },
  MCP_ACTIONS: {
    path: "/admin/actions/mcp",
    icon: SvgMcp,
    title: "MCP 操作",
    sidebarLabel: "MCP 操作",
  },
  OPENAPI_ACTIONS: {
    path: "/admin/actions/open-api",
    icon: SvgActions,
    title: "OpenAPI 操作",
    sidebarLabel: "OpenAPI 操作",
  },
  STANDARD_ANSWERS: {
    path: "/admin/standard-answer",
    icon: SvgClipboard,
    title: "标准答案",
    sidebarLabel: "标准答案",
  },
  GROUPS: {
    path: "/admin/groups",
    icon: SvgUsers,
    title: "管理用户组",
    sidebarLabel: "用户组",
  },
  CHAT_PREFERENCES: {
    path: "/admin/configuration/chat-preferences",
    icon: SvgBubbleText,
    title: "聊天偏好",
    sidebarLabel: "聊天偏好",
  },
  LLM_MODELS: {
    path: "/admin/configuration/language-models",
    icon: SvgCpu,
    title: "语言模型",
    sidebarLabel: "语言模型",
  },
  WEB_SEARCH: {
    path: "/admin/configuration/web-search",
    icon: SvgGlobe,
    title: "网页搜索",
    sidebarLabel: "网页搜索",
  },
  IMAGE_GENERATION: {
    path: "/admin/configuration/image-generation",
    icon: SvgImage,
    title: "图像生成",
    sidebarLabel: "图像生成",
  },
  VOICE: {
    path: "/admin/configuration/voice",
    icon: SvgAudio,
    title: "语音",
    sidebarLabel: "语音",
  },
  CODE_INTERPRETER: {
    path: "/admin/configuration/code-interpreter",
    icon: SvgTerminal,
    title: "代码解释器",
    sidebarLabel: "代码解释器",
  },
  INDEX_SETTINGS: {
    path: "/admin/configuration/index-settings",
    icon: SvgSearchMenu,
    title: "索引设置",
    sidebarLabel: "索引设置",
  },
  DOCUMENT_PROCESSING: {
    path: "/admin/configuration/document-processing",
    icon: SvgFileText,
    title: "文档处理",
    sidebarLabel: "文档处理",
  },
  USERS: {
    path: "/admin/users",
    icon: SvgUser,
    title: "用户与申请",
    sidebarLabel: "用户",
  },
  API_KEYS: {
    path: "/admin/service-accounts",
    icon: SvgUserKey,
    title: "服务账号",
    sidebarLabel: "服务账号",
  },
  TOKEN_RATE_LIMITS: {
    path: "/admin/token-rate-limits",
    icon: SvgProgressBars,
    title: "费用限制",
    sidebarLabel: "费用限制",
  },
  USAGE: {
    path: "/admin/performance/usage",
    icon: SvgActivity,
    title: "使用统计",
    sidebarLabel: "使用统计",
  },
  QUERY_HISTORY: {
    path: "/admin/performance/query-history",
    icon: SvgHistory,
    title: "查询历史",
    sidebarLabel: "查询历史",
  },
  CUSTOM_ANALYTICS: {
    path: "/admin/performance/custom-analytics",
    icon: SvgBarChart,
    title: "自定义分析",
    sidebarLabel: "自定义分析",
  },
  THEME: {
    path: "/admin/theme",
    icon: SvgPaintBrush,
    title: "外观与主题",
    sidebarLabel: "外观与主题",
  },
  BILLING: {
    path: "/admin/billing",
    icon: SvgWallet,
    title: "套餐与账单",
    sidebarLabel: "套餐与账单",
  },
  HOOKS: {
    path: "/admin/hooks",
    icon: SvgShareWebhook,
    title: "Hook 扩展",
    sidebarLabel: "Hook 扩展",
  },
  SCIM: {
    path: "/admin/scim",
    icon: SvgUserSync,
    title: "SCIM",
    sidebarLabel: "SCIM",
  },
  DEBUG: {
    path: "/admin/debug",
    icon: SvgDownload,
    title: "调试日志",
    sidebarLabel: "调试日志",
  },
  SECURITY_HARDENING: {
    path: "/admin/security",
    icon: SvgShield,
    title: "安全加固",
    sidebarLabel: "安全加固",
  },
  // Prefix-only entries used for layout matching — not rendered as sidebar
  // items or page headers.
  DOCUMENTS: {
    path: "/admin/documents",
    icon: SvgEmpty,
    title: "",
    sidebarLabel: "",
  },
  PERFORMANCE: {
    path: "/admin/performance",
    icon: SvgEmpty,
    title: "",
    sidebarLabel: "",
  },
} as const satisfies Record<string, AdminRouteEntry>;

/**
 * Helper that converts a route entry into the `{ name, icon, link }`
 * shape expected by the sidebar.
 */
export function sidebarItem(route: AdminRouteEntry) {
  return { name: route.sidebarLabel, icon: route.icon, link: route.path };
}

/**
 * Connector/indexing admin route prefixes that need a vector DB. In Lite mode
 * these render an informational notice instead of their normal content.
 */
export const VECTOR_DB_REQUIRED_ROUTE_PREFIXES: readonly string[] = [
  ADMIN_ROUTES.INDEXING_STATUS.path,
  ADMIN_ROUTES.ADD_CONNECTOR.path,
  // Covers /sets, /explorer, and /feedback — all require a vector DB.
  ADMIN_ROUTES.DOCUMENTS.path,
  ADMIN_ROUTES.INDEX_SETTINGS.path,
  "/admin/connector",
  "/admin/federated",
];

export function isVectorDbRequiredRoute(pathname: string): boolean {
  return VECTOR_DB_REQUIRED_ROUTE_PREFIXES.some((prefix) =>
    pathname.startsWith(prefix)
  );
}
