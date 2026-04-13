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
  SvgDiscordMono,
  SvgDownload,
  SvgEmpty,
  SvgFileText,
  SvgFiles,
  SvgGlobe,
  SvgHistory,
  SvgImage,
  SvgMcp,
  SvgNetworkGraph,
  SvgOnyxOctagon,
  SvgPaintBrush,
  SvgProgressBars,
  SvgSearchMenu,
  SvgSlack,
  SvgTerminal,
  SvgThumbsUp,
  SvgUploadCloud,
  SvgUser,
  SvgUserKey,
  SvgUserSync,
  SvgUsers,
  SvgWallet,
  SvgZoomIn,
} from "@opal/icons";

export interface FeatureFlags {
  vectorDbEnabled: boolean;
  kgExposed: boolean;
  enableCloud: boolean;
  enableEnterprise: boolean;
  customAnalyticsEnabled: boolean;
  hasSubscription: boolean;
  hooksEnabled: boolean;
  opensearchEnabled: boolean;
  queryHistoryEnabled: boolean;
}

export interface AdminRouteEntry {
  path: string;
  icon: IconFunctionComponent;
  title: string;
  sidebarLabel: string;
  requiredPermission: string;
  section: string;
  requiresEnterprise: boolean;
  visibleWhen: ((flags: FeatureFlags) => boolean) | null;
}

export const ADMIN_ROUTES = {
  // ── System Configuration (unlabeled section) ──────────────────────
  LLM_MODELS: {
    path: "/admin/configuration/llm",
    icon: SvgCpu,
    title: "Language Models",
    sidebarLabel: "Language Models",
    requiredPermission: "manage:llms",
    section: "",
    requiresEnterprise: false,
    visibleWhen: null,
  },
  WEB_SEARCH: {
    path: "/admin/configuration/web-search",
    icon: SvgGlobe,
    title: "Web Search",
    sidebarLabel: "Web Search",
    requiredPermission: "admin",
    section: "",
    requiresEnterprise: false,
    visibleWhen: null,
  },
  IMAGE_GENERATION: {
    path: "/admin/configuration/image-generation",
    icon: SvgImage,
    title: "Image Generation",
    sidebarLabel: "Image Generation",
    requiredPermission: "admin",
    section: "",
    requiresEnterprise: false,
    visibleWhen: null,
  },
  VOICE: {
    path: "/admin/configuration/voice",
    icon: SvgAudio,
    title: "Voice",
    sidebarLabel: "Voice",
    requiredPermission: "admin",
    section: "",
    requiresEnterprise: false,
    visibleWhen: null,
  },
  CODE_INTERPRETER: {
    path: "/admin/configuration/code-interpreter",
    icon: SvgTerminal,
    title: "Code Interpreter",
    sidebarLabel: "Code Interpreter",
    requiredPermission: "admin",
    section: "",
    requiresEnterprise: false,
    visibleWhen: null,
  },
  CHAT_PREFERENCES: {
    path: "/admin/configuration/chat-preferences",
    icon: SvgBubbleText,
    title: "Chat Preferences",
    sidebarLabel: "Chat Preferences",
    requiredPermission: "admin",
    section: "",
    requiresEnterprise: false,
    visibleWhen: null,
  },
  KNOWLEDGE_GRAPH: {
    path: "/admin/kg",
    icon: SvgNetworkGraph,
    title: "Knowledge Graph",
    sidebarLabel: "Knowledge Graph",
    requiredPermission: "admin",
    section: "",
    requiresEnterprise: false,
    visibleWhen: (f: FeatureFlags) => f.vectorDbEnabled && f.kgExposed,
  },
  CUSTOM_ANALYTICS: {
    path: "/admin/performance/custom-analytics",
    icon: SvgBarChart,
    title: "Custom Analytics",
    sidebarLabel: "Custom Analytics",
    requiredPermission: "admin",
    section: "",
    requiresEnterprise: true,
    visibleWhen: (f: FeatureFlags) =>
      !f.enableCloud && f.customAnalyticsEnabled,
  },

  // ── Agents & Actions ──────────────────────────────────────────────
  AGENTS: {
    path: "/admin/agents",
    icon: SvgOnyxOctagon,
    title: "Agents",
    sidebarLabel: "Agents",
    requiredPermission: "manage:agents",
    section: "Agents & Actions",
    requiresEnterprise: false,
    visibleWhen: null,
  },
  MCP_ACTIONS: {
    path: "/admin/actions/mcp",
    icon: SvgMcp,
    title: "MCP Actions",
    sidebarLabel: "MCP Actions",
    requiredPermission: "manage:actions",
    section: "Agents & Actions",
    requiresEnterprise: false,
    visibleWhen: null,
  },
  OPENAPI_ACTIONS: {
    path: "/admin/actions/open-api",
    icon: SvgActions,
    title: "OpenAPI Actions",
    sidebarLabel: "OpenAPI Actions",
    requiredPermission: "manage:actions",
    section: "Agents & Actions",
    requiresEnterprise: false,
    visibleWhen: null,
  },

  // ── Documents & Knowledge ─────────────────────────────────────────
  INDEXING_STATUS: {
    path: "/admin/indexing/status",
    icon: SvgBookOpen,
    title: "Existing Connectors",
    sidebarLabel: "Existing Connectors",
    requiredPermission: "manage:connectors",
    section: "Documents & Knowledge",
    requiresEnterprise: false,
    visibleWhen: (f: FeatureFlags) => f.vectorDbEnabled,
  },
  ADD_CONNECTOR: {
    path: "/admin/add-connector",
    icon: SvgUploadCloud,
    title: "Add Connector",
    sidebarLabel: "Add Connector",
    requiredPermission: "manage:connectors",
    section: "Documents & Knowledge",
    requiresEnterprise: false,
    visibleWhen: (f: FeatureFlags) => f.vectorDbEnabled,
  },
  DOCUMENT_SETS: {
    path: "/admin/documents/sets",
    icon: SvgFiles,
    title: "Document Sets",
    sidebarLabel: "Document Sets",
    requiredPermission: "manage:document_sets",
    section: "Documents & Knowledge",
    requiresEnterprise: false,
    visibleWhen: (f: FeatureFlags) => f.vectorDbEnabled,
  },
  DOCUMENT_EXPLORER: {
    path: "/admin/documents/explorer",
    icon: SvgZoomIn,
    title: "Document Explorer",
    sidebarLabel: "",
    requiredPermission: "admin",
    section: "Documents & Knowledge",
    requiresEnterprise: false,
    visibleWhen: (f: FeatureFlags) => f.vectorDbEnabled,
  },
  DOCUMENT_FEEDBACK: {
    path: "/admin/documents/feedback",
    icon: SvgThumbsUp,
    title: "Document Feedback",
    sidebarLabel: "",
    requiredPermission: "admin",
    section: "Documents & Knowledge",
    requiresEnterprise: false,
    visibleWhen: (f: FeatureFlags) => f.vectorDbEnabled,
  },
  INDEX_SETTINGS: {
    path: "/admin/configuration/search",
    icon: SvgSearchMenu,
    title: "Index Settings",
    sidebarLabel: "Index Settings",
    requiredPermission: "admin",
    section: "Documents & Knowledge",
    requiresEnterprise: false,
    visibleWhen: (f: FeatureFlags) => f.vectorDbEnabled && !f.enableCloud,
  },
  DOCUMENT_PROCESSING: {
    path: "/admin/configuration/document-processing",
    icon: SvgFileText,
    title: "Document Processing",
    sidebarLabel: "",
    requiredPermission: "admin",
    section: "Documents & Knowledge",
    requiresEnterprise: false,
    visibleWhen: (f: FeatureFlags) => f.vectorDbEnabled,
  },
  INDEX_MIGRATION: {
    path: "/admin/document-index-migration",
    icon: SvgArrowExchange,
    title: "Document Index Migration",
    sidebarLabel: "Document Index Migration",
    requiredPermission: "admin",
    section: "Documents & Knowledge",
    requiresEnterprise: false,
    visibleWhen: (f: FeatureFlags) => f.vectorDbEnabled && f.opensearchEnabled,
  },

  // ── Integrations ──────────────────────────────────────────────────
  API_KEYS: {
    path: "/admin/service-accounts",
    icon: SvgUserKey,
    title: "Service Accounts",
    sidebarLabel: "Service Accounts",
    requiredPermission: "manage:service_account_api_keys",
    section: "Integrations",
    requiresEnterprise: false,
    visibleWhen: null,
  },
  SLACK_BOTS: {
    path: "/admin/bots",
    icon: SvgSlack,
    title: "Slack Integration",
    sidebarLabel: "Slack Integration",
    requiredPermission: "manage:bots",
    section: "Integrations",
    requiresEnterprise: false,
    visibleWhen: null,
  },
  DISCORD_BOTS: {
    path: "/admin/discord-bot",
    icon: SvgDiscordMono,
    title: "Discord Integration",
    sidebarLabel: "Discord Integration",
    requiredPermission: "manage:bots",
    section: "Integrations",
    requiresEnterprise: false,
    visibleWhen: null,
  },
  HOOKS: {
    path: "/admin/hooks",
    icon: SvgShareWebhook,
    title: "Hook Extensions",
    sidebarLabel: "Hook Extensions",
    requiredPermission: "admin",
    section: "Integrations",
    requiresEnterprise: false,
    visibleWhen: (f: FeatureFlags) => f.hooksEnabled,
  },

  // ── Permissions ───────────────────────────────────────────────────
  USERS: {
    path: "/admin/users",
    icon: SvgUser,
    title: "Users & Requests",
    sidebarLabel: "Users",
    requiredPermission: "admin",
    section: "Permissions",
    requiresEnterprise: false,
    visibleWhen: null,
  },
  GROUPS: {
    path: "/admin/groups",
    icon: SvgUsers,
    title: "Manage User Groups",
    sidebarLabel: "Groups",
    requiredPermission: "admin",
    section: "Permissions",
    requiresEnterprise: true,
    visibleWhen: null,
  },
  SCIM: {
    path: "/admin/scim",
    icon: SvgUserSync,
    title: "SCIM",
    sidebarLabel: "SCIM",
    requiredPermission: "admin",
    section: "Permissions",
    requiresEnterprise: true,
    visibleWhen: null,
  },

  // ── Organization ──────────────────────────────────────────────────
  BILLING: {
    path: "/admin/billing",
    icon: SvgWallet,
    title: "Plans & Billing",
    sidebarLabel: "Plans & Billing",
    requiredPermission: "admin",
    section: "Organization",
    requiresEnterprise: false,
    visibleWhen: (f: FeatureFlags) => f.hasSubscription,
  },
  TOKEN_RATE_LIMITS: {
    path: "/admin/token-rate-limits",
    icon: SvgProgressBars,
    title: "Spending Limits",
    sidebarLabel: "Spending Limits",
    requiredPermission: "admin",
    section: "Organization",
    requiresEnterprise: true,
    visibleWhen: null,
  },
  THEME: {
    path: "/admin/theme",
    icon: SvgPaintBrush,
    title: "Appearance & Theming",
    sidebarLabel: "Appearance & Theming",
    requiredPermission: "admin",
    section: "Organization",
    requiresEnterprise: true,
    visibleWhen: null,
  },

  // ── Usage ─────────────────────────────────────────────────────────
  USAGE: {
    path: "/admin/performance/usage",
    icon: SvgActivity,
    title: "Usage Statistics",
    sidebarLabel: "Usage Statistics",
    requiredPermission: "admin",
    section: "Usage",
    requiresEnterprise: true,
    visibleWhen: null,
  },
  QUERY_HISTORY: {
    path: "/admin/performance/query-history",
    icon: SvgHistory,
    title: "Query History",
    sidebarLabel: "Query History",
    requiredPermission: "read:query_history",
    section: "Usage",
    requiresEnterprise: true,
    visibleWhen: (f: FeatureFlags) => f.queryHistoryEnabled,
  },

  // ── Other (admin-only) ────────────────────────────────────────────
  STANDARD_ANSWERS: {
    path: "/admin/standard-answer",
    icon: SvgClipboard,
    title: "Standard Answers",
    sidebarLabel: "",
    requiredPermission: "admin",
    section: "",
    requiresEnterprise: false,
    visibleWhen: null,
  },
  DEBUG: {
    path: "/admin/debug",
    icon: SvgDownload,
    title: "Debug Logs",
    sidebarLabel: "",
    requiredPermission: "admin",
    section: "",
    requiresEnterprise: false,
    visibleWhen: null,
  },

  // ── Prefix-only entries (layout matching, not sidebar items) ──────
  DOCUMENTS: {
    path: "/admin/documents",
    icon: SvgEmpty,
    title: "",
    sidebarLabel: "",
    requiredPermission: "admin",
    section: "",
    requiresEnterprise: false,
    visibleWhen: null,
  },
  PERFORMANCE: {
    path: "/admin/performance",
    icon: SvgEmpty,
    title: "",
    sidebarLabel: "",
    requiredPermission: "admin",
    section: "",
    requiresEnterprise: false,
    visibleWhen: null,
  },
} as const satisfies Record<string, AdminRouteEntry>;

/**
 * Helper that converts a route entry into the `{ name, icon, link }`
 * shape expected by the sidebar.
 */
export function sidebarItem(route: AdminRouteEntry) {
  return { name: route.sidebarLabel, icon: route.icon, link: route.path };
}
