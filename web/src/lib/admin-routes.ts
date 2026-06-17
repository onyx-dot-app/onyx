import { Permission } from "@/lib/types";
import { Tier } from "@/interfaces/settings";
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
} from "@opal/icons";

export interface FeatureFlags {
  vectorDbEnabled: boolean;
  enableCloud: boolean;
  tier: Tier | undefined;
  customAnalyticsEnabled: boolean;
  hasSubscription: boolean;
  hooksEnabled: boolean;
  opensearchEnabled: boolean;
  queryHistoryEnabled: boolean;
}

/**
 * Declarative metadata for a single admin-panel route. Drives both the
 * sidebar (in `admin-sidebar-utils.ts`) and the per-page permission gate
 * (in `ClientLayout.tsx`).
 *
 * Fields:
 * - `path`: Route path. Used for matching the current pathname (via
 *   `pathname.startsWith(path)`) and as the link target in the sidebar.
 * - `icon`: Icon shown next to the sidebar label.
 * - `title`: Human-readable page title (currently used for documentation
 *   and potential future page headers).
 * - `sidebarLabel`: Text shown in the sidebar. **An empty string means the
 *   route is permission-gated and layout-matched but does not render in the
 *   sidebar** (e.g. deep-link-only or hidden admin tools like `/admin/debug`).
 * - `requiredPermission`: The single `Permission` token the user must hold
 *   to access this route. `FULL_ADMIN_PANEL_ACCESS` overrides every other
 *   permission. There is no "any-of" — gate only on a single token.
 * - `section`: Sidebar grouping label. **An empty string places the route in
 *   the unlabeled (default) section.**
 * - `requiredTier`: Tier the workspace must be on for the route to be active.
 *   `null` means no tier requirement (always enabled). `Tier.BUSINESS` or
 *   `Tier.ENTERPRISE` cause the sidebar entry to be rendered disabled with an
 *   upsell tooltip when the current workspace tier is lower; the route still
 *   resolves so deep-linking continues to work for the EE gate UI.
 * - `visibleWhen`: Optional feature-flag predicate. **`null` means always
 *   visible (subject to the permission and tier checks above).** When
 *   provided, the predicate is evaluated against the resolved feature flags;
 *   returning `false` hides the route from the sidebar.
 */
export interface AdminRouteEntry {
  path: string;
  icon: IconFunctionComponent;
  title: string;
  sidebarLabel: string;
  requiredPermission: Permission;
  section: string;
  requiredTier: Tier | null;
  visibleWhen: ((flags: FeatureFlags) => boolean) | null;
}

export const ADMIN_ROUTES = {
  // ── System Configuration (unlabeled section) ──────────────────────
  LLM_MODELS: {
    path: "/admin/configuration/language-models",
    icon: SvgCpu,
    title: "Language Models",
    sidebarLabel: "Language Models",
    requiredPermission: Permission.MANAGE_LLMS,
    section: "",
    requiredTier: null,
    visibleWhen: null,
  },
  WEB_SEARCH: {
    path: "/admin/configuration/web-search",
    icon: SvgGlobe,
    title: "Web Search",
    sidebarLabel: "Web Search",
    requiredPermission: Permission.FULL_ADMIN_PANEL_ACCESS,
    section: "",
    requiredTier: null,
    visibleWhen: null,
  },
  IMAGE_GENERATION: {
    path: "/admin/configuration/image-generation",
    icon: SvgImage,
    title: "Image Generation",
    sidebarLabel: "Image Generation",
    requiredPermission: Permission.FULL_ADMIN_PANEL_ACCESS,
    section: "",
    requiredTier: null,
    visibleWhen: null,
  },
  VOICE: {
    path: "/admin/configuration/voice",
    icon: SvgAudio,
    title: "Voice",
    sidebarLabel: "Voice",
    requiredPermission: Permission.FULL_ADMIN_PANEL_ACCESS,
    section: "",
    requiredTier: null,
    visibleWhen: null,
  },
  CODE_INTERPRETER: {
    path: "/admin/configuration/code-interpreter",
    icon: SvgTerminal,
    title: "Code Interpreter",
    sidebarLabel: "Code Interpreter",
    requiredPermission: Permission.FULL_ADMIN_PANEL_ACCESS,
    section: "",
    requiredTier: null,
    visibleWhen: null,
  },
  CHAT_PREFERENCES: {
    path: "/admin/configuration/chat-preferences",
    icon: SvgBubbleText,
    title: "Chat Preferences",
    sidebarLabel: "Chat Preferences",
    requiredPermission: Permission.FULL_ADMIN_PANEL_ACCESS,
    section: "",
    requiredTier: null,
    visibleWhen: null,
  },
  CUSTOM_ANALYTICS: {
    path: "/admin/performance/custom-analytics",
    icon: SvgBarChart,
    title: "Custom Analytics",
    sidebarLabel: "Custom Analytics",
    requiredPermission: Permission.FULL_ADMIN_PANEL_ACCESS,
    section: "",
    requiredTier: Tier.ENTERPRISE,
    visibleWhen: (f: FeatureFlags) =>
      !f.enableCloud && f.customAnalyticsEnabled,
  },

  // ── Agents & Actions ──────────────────────────────────────────────
  AGENTS: {
    path: "/admin/agents",
    icon: SvgOnyxOctagon,
    title: "Agents",
    sidebarLabel: "Agents",
    requiredPermission: Permission.MANAGE_AGENTS,
    section: "Agents & Actions",
    requiredTier: null,
    visibleWhen: null,
  },
  MCP_ACTIONS: {
    path: "/admin/actions/mcp",
    icon: SvgMcp,
    title: "MCP Actions",
    sidebarLabel: "MCP Actions",
    requiredPermission: Permission.MANAGE_ACTIONS,
    section: "Agents & Actions",
    requiredTier: null,
    visibleWhen: null,
  },
  OPENAPI_ACTIONS: {
    path: "/admin/actions/open-api",
    icon: SvgActions,
    title: "OpenAPI Actions",
    sidebarLabel: "OpenAPI Actions",
    requiredPermission: Permission.MANAGE_ACTIONS,
    section: "Agents & Actions",
    requiredTier: null,
    visibleWhen: null,
  },

  // ── Documents & Knowledge ─────────────────────────────────────────
  INDEXING_STATUS: {
    path: "/admin/indexing/status",
    icon: SvgBookOpen,
    title: "Existing Connectors",
    sidebarLabel: "Existing Connectors",
    requiredPermission: Permission.MANAGE_CONNECTORS,
    section: "Documents & Knowledge",
    requiredTier: null,
    visibleWhen: (f: FeatureFlags) => f.vectorDbEnabled,
  },
  ADD_CONNECTOR: {
    path: "/admin/add-connector",
    icon: SvgUploadCloud,
    title: "Add Connector",
    sidebarLabel: "Add Connector",
    requiredPermission: Permission.MANAGE_CONNECTORS,
    section: "Documents & Knowledge",
    requiredTier: null,
    visibleWhen: (f: FeatureFlags) => f.vectorDbEnabled,
  },
  DOCUMENT_SETS: {
    path: "/admin/documents/sets",
    icon: SvgFiles,
    title: "Document Sets",
    sidebarLabel: "Document Sets",
    requiredPermission: Permission.MANAGE_DOCUMENT_SETS,
    section: "Documents & Knowledge",
    requiredTier: null,
    visibleWhen: (f: FeatureFlags) => f.vectorDbEnabled,
  },
  DOCUMENT_EXPLORER: {
    path: "/admin/documents/explorer",
    icon: SvgZoomIn,
    title: "Document Explorer",
    sidebarLabel: "",
    requiredPermission: Permission.FULL_ADMIN_PANEL_ACCESS,
    section: "Documents & Knowledge",
    requiredTier: null,
    visibleWhen: (f: FeatureFlags) => f.vectorDbEnabled,
  },
  DOCUMENT_FEEDBACK: {
    path: "/admin/documents/feedback",
    icon: SvgThumbsUp,
    title: "Document Feedback",
    sidebarLabel: "",
    requiredPermission: Permission.FULL_ADMIN_PANEL_ACCESS,
    section: "Documents & Knowledge",
    requiredTier: null,
    visibleWhen: (f: FeatureFlags) => f.vectorDbEnabled,
  },
  INDEX_SETTINGS: {
    path: "/admin/configuration/index-settings",
    icon: SvgSearchMenu,
    title: "Index Settings",
    sidebarLabel: "Index Settings",
    requiredPermission: Permission.FULL_ADMIN_PANEL_ACCESS,
    section: "Documents & Knowledge",
    requiredTier: null,
    visibleWhen: (f: FeatureFlags) => f.vectorDbEnabled && !f.enableCloud,
  },
  DOCUMENT_PROCESSING: {
    path: "/admin/configuration/document-processing",
    icon: SvgFileText,
    title: "Document Processing",
    sidebarLabel: "",
    requiredPermission: Permission.FULL_ADMIN_PANEL_ACCESS,
    section: "Documents & Knowledge",
    requiredTier: null,
    visibleWhen: (f: FeatureFlags) => f.vectorDbEnabled,
  },
  INDEX_MIGRATION: {
    path: "/admin/document-index-migration",
    icon: SvgArrowExchange,
    title: "Document Index Migration",
    sidebarLabel: "Document Index Migration",
    requiredPermission: Permission.FULL_ADMIN_PANEL_ACCESS,
    section: "Documents & Knowledge",
    requiredTier: null,
    visibleWhen: (f: FeatureFlags) => f.vectorDbEnabled && f.opensearchEnabled,
  },

  // ── Integrations ──────────────────────────────────────────────────
  API_KEYS: {
    path: "/admin/service-accounts",
    icon: SvgUserKey,
    title: "Service Accounts",
    sidebarLabel: "Service Accounts",
    requiredPermission: Permission.MANAGE_SERVICE_ACCOUNT_API_KEYS,
    section: "Integrations",
    requiredTier: Tier.BUSINESS,
    visibleWhen: null,
  },
  SLACK_BOTS: {
    path: "/admin/bots",
    icon: SvgSlack,
    title: "Slack Integration",
    sidebarLabel: "Slack Integration",
    requiredPermission: Permission.MANAGE_BOTS,
    section: "Integrations",
    requiredTier: null,
    visibleWhen: null,
  },
  DISCORD_BOTS: {
    path: "/admin/discord-bot",
    icon: SvgDiscord,
    title: "Discord Integration",
    sidebarLabel: "Discord Integration",
    requiredPermission: Permission.MANAGE_BOTS,
    section: "Integrations",
    requiredTier: null,
    visibleWhen: null,
  },
  HOOKS: {
    path: "/admin/hooks",
    icon: SvgShareWebhook,
    title: "Hook Extensions",
    sidebarLabel: "Hook Extensions",
    requiredPermission: Permission.FULL_ADMIN_PANEL_ACCESS,
    section: "Integrations",
    requiredTier: Tier.ENTERPRISE,
    visibleWhen: (f: FeatureFlags) => f.hooksEnabled,
  },

  // ── Permissions ───────────────────────────────────────────────────
  USERS: {
    path: "/admin/users",
    icon: SvgUser,
    title: "Users & Requests",
    sidebarLabel: "Users",
    requiredPermission: Permission.FULL_ADMIN_PANEL_ACCESS,
    section: "Permissions",
    requiredTier: null,
    visibleWhen: null,
  },
  GROUPS: {
    path: "/admin/groups",
    icon: SvgUsers,
    title: "Manage User Groups",
    sidebarLabel: "Groups",
    requiredPermission: Permission.MANAGE_USER_GROUPS,
    section: "Permissions",
    requiredTier: Tier.BUSINESS,
    visibleWhen: null,
  },
  SCIM: {
    path: "/admin/scim",
    icon: SvgUserSync,
    title: "SCIM",
    sidebarLabel: "SCIM",
    requiredPermission: Permission.FULL_ADMIN_PANEL_ACCESS,
    section: "Permissions",
    requiredTier: Tier.ENTERPRISE,
    visibleWhen: null,
  },

  // ── Organization ──────────────────────────────────────────────────
  BILLING: {
    path: "/admin/billing",
    icon: SvgWallet,
    title: "Plans & Billing",
    sidebarLabel: "Plans & Billing",
    requiredPermission: Permission.FULL_ADMIN_PANEL_ACCESS,
    section: "Organization",
    requiredTier: null,
    visibleWhen: (f: FeatureFlags) => f.hasSubscription,
  },
  TOKEN_RATE_LIMITS: {
    path: "/admin/token-rate-limits",
    icon: SvgProgressBars,
    title: "Spending Limits",
    sidebarLabel: "Spending Limits",
    requiredPermission: Permission.FULL_ADMIN_PANEL_ACCESS,
    section: "Organization",
    requiredTier: Tier.ENTERPRISE,
    visibleWhen: null,
  },
  THEME: {
    path: "/admin/theme",
    icon: SvgPaintBrush,
    title: "Appearance & Theming",
    sidebarLabel: "Appearance & Theming",
    requiredPermission: Permission.FULL_ADMIN_PANEL_ACCESS,
    section: "Organization",
    requiredTier: Tier.BUSINESS,
    visibleWhen: null,
  },
  SECURITY_HARDENING: {
    path: "/admin/security",
    icon: SvgShield,
    title: "Security & Hardening",
    sidebarLabel: "Security & Hardening",
    requiredPermission: Permission.FULL_ADMIN_PANEL_ACCESS,
    section: "Organization",
    requiredTier: null,
    visibleWhen: null,
  },

  // ── Usage ─────────────────────────────────────────────────────────
  USAGE: {
    path: "/admin/performance/usage",
    icon: SvgActivity,
    title: "Usage Statistics",
    sidebarLabel: "Usage Statistics",
    requiredPermission: Permission.FULL_ADMIN_PANEL_ACCESS,
    section: "Usage",
    requiredTier: Tier.BUSINESS,
    visibleWhen: null,
  },
  QUERY_HISTORY: {
    path: "/admin/performance/query-history",
    icon: SvgHistory,
    title: "Query History",
    sidebarLabel: "Query History",
    requiredPermission: Permission.READ_QUERY_HISTORY,
    section: "Usage",
    requiredTier: Tier.BUSINESS,
    visibleWhen: (f: FeatureFlags) => f.queryHistoryEnabled,
  },

  // ── Other (admin-only) ────────────────────────────────────────────
  STANDARD_ANSWERS: {
    path: "/admin/standard-answer",
    icon: SvgClipboard,
    title: "Standard Answers",
    sidebarLabel: "",
    requiredPermission: Permission.FULL_ADMIN_PANEL_ACCESS,
    section: "",
    requiredTier: null,
    visibleWhen: null,
  },
  DEBUG: {
    path: "/admin/debug",
    icon: SvgDownload,
    title: "Debug Logs",
    sidebarLabel: "",
    requiredPermission: Permission.FULL_ADMIN_PANEL_ACCESS,
    section: "",
    requiredTier: null,
    visibleWhen: null,
  },

  // ── Prefix-only entries (layout matching, not sidebar items) ──────
  DOCUMENTS: {
    path: "/admin/documents",
    icon: SvgEmpty,
    title: "",
    sidebarLabel: "",
    requiredPermission: Permission.FULL_ADMIN_PANEL_ACCESS,
    section: "",
    requiredTier: null,
    visibleWhen: null,
  },
  PERFORMANCE: {
    path: "/admin/performance",
    icon: SvgEmpty,
    title: "",
    sidebarLabel: "",
    requiredPermission: Permission.FULL_ADMIN_PANEL_ACCESS,
    section: "",
    requiredTier: null,
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
