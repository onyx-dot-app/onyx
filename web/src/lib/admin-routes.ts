import { IconFunctionComponent } from "@opal/types";
import {
  SvgActions,
  SvgActivity,
  SvgArrowExchange,
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
  SvgOnyxOctagon,
  SvgPaintBrush,
  SvgProgressBars,
  SvgSearchMenu,
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
    title: "Existing Connectors",
    sidebarLabel: "Existing Connectors",
  },
  ADD_CONNECTOR: {
    path: "/admin/add-connector",
    icon: SvgUploadCloud,
    title: "Add Connector",
    sidebarLabel: "Add Connector",
  },
  DOCUMENT_SETS: {
    path: "/admin/documents/sets",
    icon: SvgFiles,
    title: "Document Sets",
    sidebarLabel: "Document Sets",
  },
  DOCUMENT_EXPLORER: {
    path: "/admin/documents/explorer",
    icon: SvgZoomIn,
    title: "Document Explorer",
    sidebarLabel: "Explorer",
  },
  DOCUMENT_FEEDBACK: {
    path: "/admin/documents/feedback",
    icon: SvgThumbsUp,
    title: "Document Feedback",
    sidebarLabel: "Feedback",
  },
  AGENTS: {
    path: "/admin/agents",
    icon: SvgOnyxOctagon,
    title: "Agents",
    sidebarLabel: "Agents",
  },
  SLACK_BOTS: {
    path: "/admin/bots",
    icon: SvgSlack,
    title: "Slack Integration",
    sidebarLabel: "Slack Integration",
  },
  DISCORD_BOTS: {
    path: "/admin/discord-bot",
    icon: SvgDiscord,
    title: "Discord Integration",
    sidebarLabel: "Discord Integration",
  },
  MCP_ACTIONS: {
    path: "/admin/actions/mcp",
    icon: SvgMcp,
    title: "MCP Actions",
    sidebarLabel: "MCP Actions",
  },
  OPENAPI_ACTIONS: {
    path: "/admin/actions/open-api",
    icon: SvgActions,
    title: "OpenAPI Actions",
    sidebarLabel: "OpenAPI Actions",
  },
  STANDARD_ANSWERS: {
    path: "/admin/standard-answer",
    icon: SvgClipboard,
    title: "Standard Answers",
    sidebarLabel: "Standard Answers",
  },
  GROUPS: {
    path: "/admin/groups",
    icon: SvgUsers,
    title: "Manage User Groups",
    sidebarLabel: "Groups",
  },
  CHAT_PREFERENCES: {
    path: "/admin/configuration/chat-preferences",
    icon: SvgBubbleText,
    title: "Chat Preferences",
    sidebarLabel: "Chat Preferences",
  },
  LLM_MODELS: {
    path: "/admin/configuration/llm",
    icon: SvgCpu,
    title: "Language Models",
    sidebarLabel: "Language Models",
  },
  WEB_SEARCH: {
    path: "/admin/configuration/web-search",
    icon: SvgGlobe,
    title: "Web Search",
    sidebarLabel: "Web Search",
  },
  IMAGE_GENERATION: {
    path: "/admin/configuration/image-generation",
    icon: SvgImage,
    title: "Image Generation",
    sidebarLabel: "Image Generation",
  },
  VOICE: {
    path: "/admin/configuration/voice",
    icon: SvgAudio,
    title: "Voice",
    sidebarLabel: "Voice",
  },
  CODE_INTERPRETER: {
    path: "/admin/configuration/code-interpreter",
    icon: SvgTerminal,
    title: "Code Interpreter",
    sidebarLabel: "Code Interpreter",
  },
  INDEX_SETTINGS: {
    path: "/admin/configuration/search",
    icon: SvgSearchMenu,
    title: "Index Settings",
    sidebarLabel: "Index Settings",
  },
  DOCUMENT_PROCESSING: {
    path: "/admin/configuration/document-processing",
    icon: SvgFileText,
    title: "Document Processing",
    sidebarLabel: "Document Processing",
  },
  USERS: {
    path: "/admin/users",
    icon: SvgUser,
    title: "Users & Requests",
    sidebarLabel: "Users",
  },
  API_KEYS: {
    path: "/admin/service-accounts",
    icon: SvgUserKey,
    title: "Service Accounts",
    sidebarLabel: "Service Accounts",
  },
  TOKEN_RATE_LIMITS: {
    path: "/admin/token-rate-limits",
    icon: SvgProgressBars,
    title: "Spending Limits",
    sidebarLabel: "Spending Limits",
  },
  USAGE: {
    path: "/admin/performance/usage",
    icon: SvgActivity,
    title: "Usage Statistics",
    sidebarLabel: "Usage Statistics",
  },
  QUERY_HISTORY: {
    path: "/admin/performance/query-history",
    icon: SvgHistory,
    title: "Query History",
    sidebarLabel: "Query History",
  },
  CUSTOM_ANALYTICS: {
    path: "/admin/performance/custom-analytics",
    icon: SvgBarChart,
    title: "Custom Analytics",
    sidebarLabel: "Custom Analytics",
  },
  THEME: {
    path: "/admin/theme",
    icon: SvgPaintBrush,
    title: "Appearance & Theming",
    sidebarLabel: "Appearance & Theming",
  },
  BILLING: {
    path: "/admin/billing",
    icon: SvgWallet,
    title: "Plans & Billing",
    sidebarLabel: "Plans & Billing",
  },
  INDEX_MIGRATION: {
    path: "/admin/document-index-migration",
    icon: SvgArrowExchange,
    title: "Document Index Migration",
    sidebarLabel: "Document Index Migration",
  },
  HOOKS: {
    path: "/admin/hooks",
    icon: SvgShareWebhook,
    title: "Hook Extensions",
    sidebarLabel: "Hook Extensions",
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
    title: "Debug Logs",
    sidebarLabel: "Debug Logs",
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
