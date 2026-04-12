"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import { usePathname } from "next/navigation";
import { useSettingsContext } from "@/providers/SettingsProvider";
import SidebarSection from "@/sections/sidebar/SidebarSection";
import * as SidebarLayouts from "@/layouts/sidebar-layouts";
import { useSidebarFolded } from "@/layouts/sidebar-layouts";
import { useIsKGExposed } from "@/app/admin/kg/utils";
import { useCustomAnalyticsEnabled } from "@/lib/hooks/useCustomAnalyticsEnabled";
import { useUser } from "@/providers/UserProvider";
import { UserRole } from "@/lib/types";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import { CombinedSettings } from "@/interfaces/settings";
import { SidebarTab } from "@opal/components";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import Separator from "@/refresh-components/Separator";
import Spacer from "@/refresh-components/Spacer";
import { SvgArrowUpCircle, SvgSearch, SvgX } from "@opal/icons";
import {
  useBillingInformation,
  useLicense,
  hasActiveSubscription,
} from "@/lib/billing";
import { ADMIN_ROUTES, sidebarItem } from "@/lib/admin-routes";
import useFilter from "@/hooks/useFilter";
import { IconFunctionComponent } from "@opal/types";
import AccountPopover from "@/sections/sidebar/AccountPopover";
import { useTranslations } from "next-intl";

// Section key mapping for translated labels
const SECTION_KEY_MAP: Record<string, string> = {
  UNLABELED: "",
  AGENTS_AND_ACTIONS: "agentsAndActions",
  DOCUMENTS_AND_KNOWLEDGE: "documentsAndKnowledge",
  INTEGRATIONS: "integrations",
  PERMISSIONS: "permissions",
  ORGANIZATION: "organization",
  USAGE: "usage",
} as const;

// Route path to admin.routes translation key mapping for sidebar labels
const ROUTE_LABEL_KEY_MAP: Record<string, string> = {
  "/admin/configuration/llm": "languageModels",
  "/admin/configuration/web-search": "webSearch",
  "/admin/configuration/image-generation": "imageGeneration",
  "/admin/configuration/voice": "voice",
  "/admin/configuration/code-interpreter": "codeInterpreter",
  "/admin/configuration/chat-preferences": "chatPreferences",
  "/admin/kg": "knowledgeGraph",
  "/admin/performance/custom-analytics": "customAnalytics",
  "/admin/agents": "agents",
  "/admin/actions/mcp": "mcpActions",
  "/admin/actions/open-api": "openapiActions",
  "/admin/indexing/status": "existingConnectors",
  "/admin/add-connector": "addConnector",
  "/admin/documents/sets": "documentSets",
  "/admin/configuration/search": "indexSettings",
  "/admin/document-index-migration": "documentIndexMigration",
  "/admin/service-accounts": "serviceAccounts",
  "/admin/bots": "slackIntegration",
  "/admin/discord-bot": "discordIntegration",
  "/admin/hooks": "hookExtensions",
  "/admin/users": "usersAndRequests",
  "/admin/groups": "groups",
  "/admin/scim": "scim",
  "/admin/billing": "plansAndBilling",
  "/admin/token-rate-limits": "spendingLimits",
  "/admin/theme": "appearanceAndTheming",
  "/admin/performance/usage": "usageStatistics",
  "/admin/performance/query-history": "queryHistory",
  "/admin/standard-answer": "standardAnswers",
  "/admin/debug": "debugLogs",
  "/admin/configuration/document-processing": "documentProcessing",
} as const;

interface SidebarItemEntry {
  sectionKey: string;
  name: string;
  icon: IconFunctionComponent;
  link: string;
  error?: boolean;
  disabled?: boolean;
}

function buildItems(
  isCurator: boolean,
  enableCloud: boolean,
  enableEnterprise: boolean,
  settings: CombinedSettings | null,
  kgExposed: boolean,
  customAnalyticsEnabled: boolean,
  hasSubscription: boolean,
  hooksEnabled: boolean
): SidebarItemEntry[] {
  const vectorDbEnabled = settings?.settings.vector_db_enabled !== false;
  const items: SidebarItemEntry[] = [];

  const add = (section: string, route: Parameters<typeof sidebarItem>[0]) => {
    items.push({ ...sidebarItem(route), sectionKey: section });
  };

  const addDisabled = (
    section: string,
    route: Parameters<typeof sidebarItem>[0],
    isDisabled: boolean
  ) => {
    items.push({ ...sidebarItem(route), sectionKey: section, disabled: isDisabled });
  };

  // 1. No header — core configuration (admin only)
  if (!isCurator) {
    add("UNLABELED", ADMIN_ROUTES.LLM_MODELS);
    add("UNLABELED", ADMIN_ROUTES.WEB_SEARCH);
    add("UNLABELED", ADMIN_ROUTES.IMAGE_GENERATION);
    add("UNLABELED", ADMIN_ROUTES.VOICE);
    add("UNLABELED", ADMIN_ROUTES.CODE_INTERPRETER);
    add("UNLABELED", ADMIN_ROUTES.CHAT_PREFERENCES);

    if (vectorDbEnabled && kgExposed) {
      add("UNLABELED", ADMIN_ROUTES.KNOWLEDGE_GRAPH);
    }

    if (!enableCloud && customAnalyticsEnabled) {
      addDisabled(
        "UNLABELED",
        ADMIN_ROUTES.CUSTOM_ANALYTICS,
        !enableEnterprise
      );
    }
  }

  // 2. Agents & Actions
  add("AGENTS_AND_ACTIONS", ADMIN_ROUTES.AGENTS);
  add("AGENTS_AND_ACTIONS", ADMIN_ROUTES.MCP_ACTIONS);
  add("AGENTS_AND_ACTIONS", ADMIN_ROUTES.OPENAPI_ACTIONS);

  // 3. Documents & Knowledge
  if (vectorDbEnabled) {
    add("DOCUMENTS_AND_KNOWLEDGE", ADMIN_ROUTES.INDEXING_STATUS);
    add("DOCUMENTS_AND_KNOWLEDGE", ADMIN_ROUTES.ADD_CONNECTOR);
    add("DOCUMENTS_AND_KNOWLEDGE", ADMIN_ROUTES.DOCUMENT_SETS);
    if (!isCurator && !enableCloud) {
      items.push({
        ...sidebarItem(ADMIN_ROUTES.INDEX_SETTINGS),
        sectionKey: "DOCUMENTS_AND_KNOWLEDGE",
        error: settings?.settings.needs_reindexing,
      });
    }
    if (!isCurator && settings?.settings.opensearch_indexing_enabled) {
      add("DOCUMENTS_AND_KNOWLEDGE", ADMIN_ROUTES.INDEX_MIGRATION);
    }
  }

  // 4. Integrations (admin only)
  if (!isCurator) {
    add("INTEGRATIONS", ADMIN_ROUTES.API_KEYS);
    add("INTEGRATIONS", ADMIN_ROUTES.SLACK_BOTS);
    add("INTEGRATIONS", ADMIN_ROUTES.DISCORD_BOTS);
    if (hooksEnabled) {
      add("INTEGRATIONS", ADMIN_ROUTES.HOOKS);
    }
  }

  // 5. Permissions
  if (!isCurator) {
    add("PERMISSIONS", ADMIN_ROUTES.USERS);
    addDisabled("PERMISSIONS", ADMIN_ROUTES.GROUPS, !enableEnterprise);
    addDisabled("PERMISSIONS", ADMIN_ROUTES.SCIM, !enableEnterprise);
  } else if (enableEnterprise) {
    add("PERMISSIONS", ADMIN_ROUTES.GROUPS);
  }

  // 6. Organization (admin only)
  if (!isCurator) {
    if (hasSubscription) {
      add("ORGANIZATION", ADMIN_ROUTES.BILLING);
    }
    addDisabled(
      "ORGANIZATION",
      ADMIN_ROUTES.TOKEN_RATE_LIMITS,
      !enableEnterprise
    );
    addDisabled("ORGANIZATION", ADMIN_ROUTES.THEME, !enableEnterprise);
  }

  // 7. Usage (admin only)
  if (!isCurator) {
    addDisabled("USAGE", ADMIN_ROUTES.USAGE, !enableEnterprise);
    if (settings?.settings.query_history_type !== "disabled") {
      addDisabled(
        "USAGE",
        ADMIN_ROUTES.QUERY_HISTORY,
        !enableEnterprise
      );
    }
  }

  return items;
}

interface AdminSidebarProps {
  enableCloudSS: boolean;
  folded: boolean;
  onFoldChange: Dispatch<SetStateAction<boolean>>;
}

interface AdminSidebarInnerProps {
  enableCloudSS: boolean;
  onFoldChange: Dispatch<SetStateAction<boolean>>;
}

function AdminSidebarInner({
  enableCloudSS,
  onFoldChange,
}: AdminSidebarInnerProps) {
  const folded = useSidebarFolded();
  const searchRef = useRef<HTMLInputElement>(null);
  const [focusSearch, setFocusSearch] = useState(false);
  const t = useTranslations("admin.sidebar");
  const ts = useTranslations("admin.sidebar.sections");
  const tr = useTranslations("admin.routes");

  useEffect(() => {
    if (focusSearch && !folded && searchRef.current) {
      searchRef.current.focus();
      setFocusSearch(false);
    }
  }, [focusSearch, folded]);
  const { kgExposed } = useIsKGExposed();
  const pathname = usePathname();
  const { customAnalyticsEnabled } = useCustomAnalyticsEnabled();
  const { user } = useUser();
  const settings = useSettingsContext();
  const enableEnterprise = usePaidEnterpriseFeaturesEnabled();
  const { data: billingData, isLoading: billingLoading } =
    useBillingInformation();
  const { data: licenseData, isLoading: licenseLoading } = useLicense();
  const isCurator =
    user?.role === UserRole.CURATOR || user?.role === UserRole.GLOBAL_CURATOR;
  // Default to true while loading to avoid flashing "Upgrade Plan"
  const hasSubscriptionOrLicense =
    billingLoading || licenseLoading
      ? true
      : Boolean(
          (billingData && hasActiveSubscription(billingData)) ||
            licenseData?.has_license
        );
  const hooksEnabled =
    enableEnterprise && (settings?.settings.hooks_enabled ?? false);

  const baseItems = buildItems(
    isCurator,
    enableCloudSS,
    enableEnterprise,
    settings,
    kgExposed,
    customAnalyticsEnabled,
    hasSubscriptionOrLicense,
    hooksEnabled
  );

  // Translate sidebar item names using admin.routes namespace
  const translatedBaseItems = baseItems.map((item) => {
    const translationKey = ROUTE_LABEL_KEY_MAP[item.link];
    if (translationKey) {
      return { ...item, name: tr(translationKey) };
    }
    return item;
  });

  // Add Upgrade Plan item with translated name
  const allItems: SidebarItemEntry[] = isCurator || hasSubscriptionOrLicense
    ? translatedBaseItems
    : [
        ...translatedBaseItems,
        {
          sectionKey: "UNLABELED",
          name: t("upgradePlan"),
          icon: SvgArrowUpCircle,
          link: ADMIN_ROUTES.BILLING.path,
        },
      ];

  // Map sectionKey to translated section label
  const getSectionLabel = (key: string) => {
    const translationKey = SECTION_KEY_MAP[key];
    return translationKey ? ts(translationKey) : "";
  };

  const itemExtractor = useCallback((item: SidebarItemEntry) => item.name, []);

  const { query, setQuery, filtered } = useFilter(allItems, itemExtractor);

  const enabled = filtered.filter((item) => !item.disabled);
  const disabledItems = filtered.filter((item) => item.disabled);

  // Group by sectionKey but render translated labels
  const groupItemsBySection = (items: SidebarItemEntry[]) => {
    const groups: { sectionKey: string; sectionLabel: string; items: SidebarItemEntry[] }[] = [];
    for (const item of items) {
      const last = groups[groups.length - 1];
      if (last && last.sectionKey === item.sectionKey) {
        last.items.push(item);
      } else {
        groups.push({
          sectionKey: item.sectionKey,
          sectionLabel: getSectionLabel(item.sectionKey),
          items: [item],
        });
      }
    }
    return groups;
  };

  const enabledGroups = groupItemsBySection(enabled);
  const disabledGroups = groupItemsBySection(disabledItems);

  return (
    <>
      <SidebarLayouts.Header>
        {folded ? (
          <SidebarTab
            icon={SvgSearch}
            folded
            onClick={() => {
              onFoldChange(false);
              setFocusSearch(true);
            }}
          >
            {t("search")}
          </SidebarTab>
        ) : (
          <InputTypeIn
            ref={searchRef}
            variant="internal"
            leftSearchIcon
            placeholder={t("search")}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        )}
      </SidebarLayouts.Header>

      <SidebarLayouts.Body scrollKey="admin-sidebar">
        {enabledGroups.map((group, groupIndex) => {
          const tabs = group.items.map(({ link, icon, name }) => (
            <SidebarTab
              key={link}
              icon={icon}
              href={link}
              selected={pathname.startsWith(link)}
            >
              {name}
            </SidebarTab>
          ));

          if (!group.sectionLabel) {
            return <div key={groupIndex}>{tabs}</div>;
          }

          return (
            <SidebarSection key={groupIndex} title={group.sectionLabel}>
              {tabs}
            </SidebarSection>
          );
        })}

        {disabledGroups.length > 0 && <Separator noPadding className="px-2" />}

        {disabledGroups.map((group, groupIndex) => (
          <SidebarSection
            key={`disabled-${groupIndex}`}
            title={group.sectionLabel}
            disabled
          >
            {group.items.map(({ link, icon, name }) => (
              <SidebarTab key={link} disabled icon={icon}>
                {name}
              </SidebarTab>
            ))}
          </SidebarSection>
        ))}
      </SidebarLayouts.Body>

      <SidebarLayouts.Footer>
        {!folded && (
          <>
            <Separator noPadding className="px-2" />
            <Spacer rem={0.5} />
          </>
        )}
        <SidebarTab
          icon={SvgX}
          href="/app"
          variant="sidebar-light"
          folded={folded}
        >
          {t("exitAdminPanel")}
        </SidebarTab>
        <AccountPopover folded={folded} />
      </SidebarLayouts.Footer>
    </>
  );
}

export default function AdminSidebar({
  enableCloudSS,
  folded,
  onFoldChange,
}: AdminSidebarProps) {
  return (
    <SidebarLayouts.Root folded={folded} onFoldChange={onFoldChange}>
      <AdminSidebarInner
        enableCloudSS={enableCloudSS}
        onFoldChange={onFoldChange}
      />
    </SidebarLayouts.Root>
  );
}
