import { IconFunctionComponent } from "@opal/types";
import {
  SvgActions,
  SvgActivity,
  SvgArrowExchange,
  SvgBarChart,
  SvgBookOpen,
  SvgBubbleText,
  SvgClipboard,
  SvgCpu,
  SvgDiscordMono,
  SvgDownload,
  SvgFileText,
  SvgFolder,
  SvgGlobe,
  SvgImage,
  SvgKey,
  SvgMcp,
  SvgNetworkGraph,
  SvgOnyxOctagon,
  SvgPaintBrush,
  SvgSearch,
  SvgServer,
  SvgShield,
  SvgSlack,
  SvgTerminal,
  SvgThumbsUp,
  SvgUploadCloud,
  SvgUser,
  SvgUserSync,
  SvgUsers,
  SvgWallet,
  SvgZoomIn,
} from "@opal/icons";

/**
 * Canonical path constants for every admin route.
 */
export const ADMIN_PATHS = {
  INDEXING_STATUS: "/admin/indexing/status",
  ADD_CONNECTOR: "/admin/add-connector",
  DOCUMENT_SETS: "/admin/documents/sets",
  DOCUMENT_EXPLORER: "/admin/documents/explorer",
  DOCUMENT_FEEDBACK: "/admin/documents/feedback",
  AGENTS: "/admin/agents",
  SLACK_BOTS: "/admin/bots",
  DISCORD_BOTS: "/admin/discord-bot",
  MCP_ACTIONS: "/admin/actions/mcp",
  OPENAPI_ACTIONS: "/admin/actions/open-api",
  STANDARD_ANSWERS: "/admin/standard-answer",
  GROUPS: "/admin/groups",
  CHAT_PREFERENCES: "/admin/configuration/chat-preferences",
  LLM_MODELS: "/admin/configuration/llm",
  WEB_SEARCH: "/admin/configuration/web-search",
  IMAGE_GENERATION: "/admin/configuration/image-generation",
  CODE_INTERPRETER: "/admin/configuration/code-interpreter",
  SEARCH_SETTINGS: "/admin/configuration/search",
  DOCUMENT_PROCESSING: "/admin/configuration/document-processing",
  KNOWLEDGE_GRAPH: "/admin/kg",
  USERS: "/admin/users",
  API_KEYS: "/admin/api-key",
  TOKEN_RATE_LIMITS: "/admin/token-rate-limits",
  USAGE: "/admin/performance/usage",
  QUERY_HISTORY: "/admin/performance/query-history",
  CUSTOM_ANALYTICS: "/admin/performance/custom-analytics",
  THEME: "/admin/theme",
  BILLING: "/admin/billing",
  INDEX_MIGRATION: "/admin/document-index-migration",
  SCIM: "/admin/scim",
  DEBUG: "/admin/debug",
  // Prefix-only entries (used in SETTINGS_LAYOUT_PREFIXES but have no
  // single page header of their own)
  DOCUMENTS: "/admin/documents",
  PERFORMANCE: "/admin/performance",
} as const;

interface AdminRouteConfig {
  icon: IconFunctionComponent;
  title: string;
  sidebarLabel: string;
}

/**
 * Single source of truth for icon, page-header title, and sidebar label
 * for every admin route. Keyed by path from `ADMIN_PATHS`.
 */
export const ADMIN_ROUTE_CONFIG: Record<string, AdminRouteConfig> = {
  [ADMIN_PATHS.INDEXING_STATUS]: {
    icon: SvgBookOpen,
    title: "Existing Connectors",
    sidebarLabel: "Existing Connectors",
  },
  [ADMIN_PATHS.ADD_CONNECTOR]: {
    icon: SvgUploadCloud,
    title: "Add Connector",
    sidebarLabel: "Add Connector",
  },
  [ADMIN_PATHS.DOCUMENT_SETS]: {
    icon: SvgFolder,
    title: "Document Sets",
    sidebarLabel: "Document Sets",
  },
  [ADMIN_PATHS.DOCUMENT_EXPLORER]: {
    icon: SvgZoomIn,
    title: "Document Explorer",
    sidebarLabel: "Explorer",
  },
  [ADMIN_PATHS.DOCUMENT_FEEDBACK]: {
    icon: SvgThumbsUp,
    title: "Document Feedback",
    sidebarLabel: "Feedback",
  },
  [ADMIN_PATHS.AGENTS]: {
    icon: SvgOnyxOctagon,
    title: "Agents",
    sidebarLabel: "Agents",
  },
  [ADMIN_PATHS.SLACK_BOTS]: {
    icon: SvgSlack,
    title: "Slack Bots",
    sidebarLabel: "Slack Bots",
  },
  [ADMIN_PATHS.DISCORD_BOTS]: {
    icon: SvgDiscordMono,
    title: "Discord Bots",
    sidebarLabel: "Discord Bots",
  },
  [ADMIN_PATHS.MCP_ACTIONS]: {
    icon: SvgMcp,
    title: "MCP Actions",
    sidebarLabel: "MCP Actions",
  },
  [ADMIN_PATHS.OPENAPI_ACTIONS]: {
    icon: SvgActions,
    title: "OpenAPI Actions",
    sidebarLabel: "OpenAPI Actions",
  },
  [ADMIN_PATHS.STANDARD_ANSWERS]: {
    icon: SvgClipboard,
    title: "Standard Answers",
    sidebarLabel: "Standard Answers",
  },
  [ADMIN_PATHS.GROUPS]: {
    icon: SvgUsers,
    title: "Manage User Groups",
    sidebarLabel: "Groups",
  },
  [ADMIN_PATHS.CHAT_PREFERENCES]: {
    icon: SvgBubbleText,
    title: "Chat Preferences",
    sidebarLabel: "Chat Preferences",
  },
  [ADMIN_PATHS.LLM_MODELS]: {
    icon: SvgCpu,
    title: "Language Models",
    sidebarLabel: "Language Models",
  },
  [ADMIN_PATHS.WEB_SEARCH]: {
    icon: SvgGlobe,
    title: "Web Search",
    sidebarLabel: "Web Search",
  },
  [ADMIN_PATHS.IMAGE_GENERATION]: {
    icon: SvgImage,
    title: "Image Generation",
    sidebarLabel: "Image Generation",
  },
  [ADMIN_PATHS.CODE_INTERPRETER]: {
    icon: SvgTerminal,
    title: "Code Interpreter",
    sidebarLabel: "Code Interpreter",
  },
  [ADMIN_PATHS.SEARCH_SETTINGS]: {
    icon: SvgSearch,
    title: "Search Settings",
    sidebarLabel: "Search Settings",
  },
  [ADMIN_PATHS.DOCUMENT_PROCESSING]: {
    icon: SvgFileText,
    title: "Document Processing",
    sidebarLabel: "Document Processing",
  },
  [ADMIN_PATHS.KNOWLEDGE_GRAPH]: {
    icon: SvgNetworkGraph,
    title: "Knowledge Graph",
    sidebarLabel: "Knowledge Graph",
  },
  [ADMIN_PATHS.USERS]: {
    icon: SvgUser,
    title: "Users & Requests",
    sidebarLabel: "Users",
  },
  [ADMIN_PATHS.API_KEYS]: {
    icon: SvgKey,
    title: "API Keys",
    sidebarLabel: "API Keys",
  },
  [ADMIN_PATHS.TOKEN_RATE_LIMITS]: {
    icon: SvgShield,
    title: "Token Rate Limits",
    sidebarLabel: "Token Rate Limits",
  },
  [ADMIN_PATHS.USAGE]: {
    icon: SvgActivity,
    title: "Usage Statistics",
    sidebarLabel: "Usage Statistics",
  },
  [ADMIN_PATHS.QUERY_HISTORY]: {
    icon: SvgServer,
    title: "Query History",
    sidebarLabel: "Query History",
  },
  [ADMIN_PATHS.CUSTOM_ANALYTICS]: {
    icon: SvgBarChart,
    title: "Custom Analytics",
    sidebarLabel: "Custom Analytics",
  },
  [ADMIN_PATHS.THEME]: {
    icon: SvgPaintBrush,
    title: "Appearance & Theming",
    sidebarLabel: "Appearance & Theming",
  },
  [ADMIN_PATHS.BILLING]: {
    icon: SvgWallet,
    title: "Plans & Billing",
    sidebarLabel: "Plans & Billing",
  },
  [ADMIN_PATHS.INDEX_MIGRATION]: {
    icon: SvgArrowExchange,
    title: "Document Index Migration",
    sidebarLabel: "Document Index Migration",
  },
  [ADMIN_PATHS.SCIM]: {
    icon: SvgUserSync,
    title: "SCIM",
    sidebarLabel: "SCIM",
  },
  [ADMIN_PATHS.DEBUG]: {
    icon: SvgDownload,
    title: "Debug Logs",
    sidebarLabel: "Debug Logs",
  },
};

/**
 * Helper that converts a route config entry into the `{ name, icon, link }`
 * shape expected by the sidebar. Extra fields (e.g. `error`) can be spread in.
 */
export function sidebarItem(path: string) {
  const config = ADMIN_ROUTE_CONFIG[path]!;
  return { name: config.sidebarLabel, icon: config.icon, link: path };
}
