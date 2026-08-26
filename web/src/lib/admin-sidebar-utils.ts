import { IconFunctionComponent } from "@opal/types";
import { SvgArrowUpCircle } from "@opal/icons";
import {
  ADMIN_ROUTES,
  AdminRouteEntry,
  FeatureFlags,
} from "@/lib/admin-routes";
import { hasPermission } from "@/lib/permissions";
import { Permission } from "@/lib/types";
import { Settings, Tier } from "@/lib/settings/types";
import { tierAtLeast } from "@/lib/tiers";

export type { FeatureFlags } from "@/lib/admin-routes";

/**
 * Stable id of one sidebar entry. The visible label is the
 * `sidebar.adminNav.items.<id>.label` message, resolved in `AdminSidebar`.
 */
export type AdminNavItemId =
  | "languageModels"
  | "webSearch"
  | "imageGeneration"
  | "voice"
  | "codeInterpreter"
  | "chatPreferences"
  | "craftAccess"
  | "craftApps"
  | "craftInstructions"
  | "customAnalytics"
  | "agents"
  | "mcpActions"
  | "openapiActions"
  | "existingConnectors"
  | "addConnector"
  | "documentSets"
  | "indexSettings"
  | "serviceAccounts"
  | "slackIntegration"
  | "discordIntegration"
  | "hookExtensions"
  | "users"
  | "groups"
  | "scim"
  | "plansAndBilling"
  | "appearanceAndTheming"
  | "securityAndHardening"
  | "ssoProviders"
  | "usage"
  | "analytics"
  | "queryHistory"
  | "tracing"
  | "exportLogs"
  | "upgradePlan";

/**
 * Stable id of one sidebar section heading. The visible label is the
 * `sidebar.adminNav.sections.<id>.label` message.
 */
export type AdminNavSectionId =
  | "craft"
  | "agentsAndActions"
  | "documentsAndKnowledge"
  | "integrations"
  | "permissions"
  | "organization"
  | "usage";

/**
 * Sidebar id per admin route. `null` marks a route that never renders in the
 * sidebar, so a new route cannot silently arrive without a label.
 */
const NAV_ITEM_IDS: Record<keyof typeof ADMIN_ROUTES, AdminNavItemId | null> = {
  LLM_MODELS: "languageModels",
  WEB_SEARCH: "webSearch",
  IMAGE_GENERATION: "imageGeneration",
  VOICE: "voice",
  CODE_INTERPRETER: "codeInterpreter",
  CHAT_PREFERENCES: "chatPreferences",
  CRAFT_ACCESS: "craftAccess",
  CRAFT_APPS: "craftApps",
  CRAFT_INSTRUCTIONS: "craftInstructions",
  CUSTOM_ANALYTICS: "customAnalytics",
  AGENTS: "agents",
  MCP_ACTIONS: "mcpActions",
  OPENAPI_ACTIONS: "openapiActions",
  INDEXING_STATUS: "existingConnectors",
  ADD_CONNECTOR: "addConnector",
  DOCUMENT_SETS: "documentSets",
  DOCUMENT_EXPLORER: null,
  DOCUMENT_FEEDBACK: null,
  INDEX_SETTINGS: "indexSettings",
  DOCUMENT_PROCESSING: null,
  API_KEYS: "serviceAccounts",
  SLACK_BOTS: "slackIntegration",
  DISCORD_BOTS: "discordIntegration",
  HOOKS: "hookExtensions",
  USERS: "users",
  GROUPS: "groups",
  SCIM: "scim",
  OAUTH_TEST: null,
  BILLING: "plansAndBilling",
  THEME: "appearanceAndTheming",
  SECURITY_HARDENING: "securityAndHardening",
  SSO_PROVIDERS: "ssoProviders",
  USAGE: "usage",
  WORKSPACE_ANALYTICS: "analytics",
  QUERY_HISTORY: "queryHistory",
  TRACING: "tracing",
  EXPORT_LOGS: "exportLogs",
  STANDARD_ANSWERS: null,
  DOCUMENTS: null,
  PERFORMANCE: null,
};

/** Section heading id per `AdminRouteEntry.section` value. */
const NAV_SECTION_IDS: readonly (readonly [
  section: string,
  id: AdminNavSectionId,
])[] = [
  ["Craft", "craft"],
  ["Agents & Actions", "agentsAndActions"],
  ["Documents & Knowledge", "documentsAndKnowledge"],
  ["Integrations", "integrations"],
  ["Permissions", "permissions"],
  ["Organization", "organization"],
  ["Usage", "usage"],
];

/** `null` for the unlabeled (default) section. */
function sectionIdFor(section: string): AdminNavSectionId | null {
  return NAV_SECTION_IDS.find(([label]) => label === section)?.[1] ?? null;
}

export interface SidebarItemEntry {
  /** `null` places the entry in the unlabeled (default) section. */
  sectionId: AdminNavSectionId | null;
  nameId: AdminNavItemId;
  icon: IconFunctionComponent;
  link: string;
  error?: boolean;
  disabled?: boolean;
  requiredTier?: Tier | null;
}

export function buildItems(
  permissions: string[],
  flags: FeatureFlags,
  settings: Settings | null
): SidebarItemEntry[] {
  const userCanAccess = (perm: string) => hasPermission(permissions, perm);
  const items: SidebarItemEntry[] = [];

  // Safety: ADMIN_ROUTES satisfies Record<string, AdminRouteEntry>, so every
  // entry pairs one of its own keys with a route.
  const routes = Object.entries(ADMIN_ROUTES) as [
    keyof typeof ADMIN_ROUTES,
    AdminRouteEntry,
  ][];

  for (const [routeKey, route] of routes) {
    const nameId = NAV_ITEM_IDS[routeKey];
    if (nameId === null) continue;
    if (!userCanAccess(route.requiredPermission)) continue;
    if (route.visibleWhen && !route.visibleWhen(flags)) continue;

    const disabled =
      route.requiredTier !== null &&
      !tierAtLeast(flags.tier, route.requiredTier);

    const item: SidebarItemEntry = {
      nameId,
      icon: route.icon,
      link: route.path,
      sectionId: sectionIdFor(route.section),
      disabled,
      requiredTier: route.requiredTier,
    };

    // INDEX_SETTINGS surfaces a reindexing-needed error indicator
    if (route.path === ADMIN_ROUTES.INDEX_SETTINGS.path) {
      item.error = settings?.needs_reindexing;
    }

    items.push(item);
  }

  if (
    userCanAccess(Permission.FULL_ADMIN_PANEL_ACCESS) &&
    !flags.hasSubscription
  ) {
    items.push({
      sectionId: null,
      nameId: "upgradePlan",
      icon: SvgArrowUpCircle,
      link: ADMIN_ROUTES.BILLING.path,
    });
  }

  return items;
}

/** Preserve section ordering while grouping consecutive items by section. */
export function groupBySection(items: SidebarItemEntry[]) {
  const groups: {
    sectionId: AdminNavSectionId | null;
    items: SidebarItemEntry[];
  }[] = [];
  for (const item of items) {
    const last = groups[groups.length - 1];
    if (last && last.sectionId === item.sectionId) {
      last.items.push(item);
    } else {
      groups.push({ sectionId: item.sectionId, items: [item] });
    }
  }
  return groups;
}
