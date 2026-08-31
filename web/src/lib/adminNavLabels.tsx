"use client";

import { useCallback, useMemo } from "react";
import { useTranslations } from "next-intl";
import { ADMIN_ROUTES, type AdminRouteEntry } from "@/lib/admin-routes";
import { NAV_ITEM_IDS, type AdminNavItemId } from "@/lib/admin-sidebar-utils";

// Built with literal keys so the message ids stay statically checkable.
export function useAdminNavLabels(): Record<AdminNavItemId, string> {
  const t = useTranslations("sidebar");
  return useMemo<Record<AdminNavItemId, string>>(
    () => ({
      languageModels: t("adminNav.items.languageModels.label"),
      webSearch: t("adminNav.items.webSearch.label"),
      imageGeneration: t("adminNav.items.imageGeneration.label"),
      voice: t("adminNav.items.voice.label"),
      codeInterpreter: t("adminNav.items.codeInterpreter.label"),
      chatPreferences: t("adminNav.items.chatPreferences.label"),
      craftAccess: t("adminNav.items.craftAccess.label"),
      craftApps: t("adminNav.items.craftApps.label"),
      craftInstructions: t("adminNav.items.craftInstructions.label"),
      customAnalytics: t("adminNav.items.customAnalytics.label"),
      agents: t("adminNav.items.agents.label"),
      mcpActions: t("adminNav.items.mcpActions.label"),
      openapiActions: t("adminNav.items.openapiActions.label"),
      existingConnectors: t("adminNav.items.existingConnectors.label"),
      addConnector: t("adminNav.items.addConnector.label"),
      documentSets: t("adminNav.items.documentSets.label"),
      indexSettings: t("adminNav.items.indexSettings.label"),
      serviceAccounts: t("adminNav.items.serviceAccounts.label"),
      slackIntegration: t("adminNav.items.slackIntegration.label"),
      discordIntegration: t("adminNav.items.discordIntegration.label"),
      hookExtensions: t("adminNav.items.hookExtensions.label"),
      users: t("adminNav.items.users.label"),
      groups: t("adminNav.items.groups.label"),
      scim: t("adminNav.items.scim.label"),
      plansAndBilling: t("adminNav.items.plansAndBilling.label"),
      appearanceAndTheming: t("adminNav.items.appearanceAndTheming.label"),
      securityAndHardening: t("adminNav.items.securityAndHardening.label"),
      ssoProviders: t("adminNav.items.ssoProviders.label"),
      usage: t("adminNav.items.usage.label"),
      analytics: t("adminNav.items.analytics.label"),
      queryHistory: t("adminNav.items.queryHistory.label"),
      tracing: t("adminNav.items.tracing.label"),
      exportLogs: t("adminNav.items.exportLogs.label"),
      upgradePlan: t("adminNav.items.upgradePlan.label"),
    }),
    [t]
  );
}

const NAV_ID_BY_PATH: Record<string, AdminNavItemId | null> =
  Object.fromEntries(
    (Object.keys(ADMIN_ROUTES) as (keyof typeof ADMIN_ROUTES)[]).map((key) => [
      ADMIN_ROUTES[key].path,
      NAV_ITEM_IDS[key],
    ])
  );

/** Nav id for a route, for server components that resolve labels themselves. */
export function getAdminNavId(route: AdminRouteEntry): AdminNavItemId | null {
  return NAV_ID_BY_PATH[route.path] ?? null;
}

// Page headers reuse the sidebar's translated labels so both stay in sync
// across locales. Routes without a nav entry fall back to their raw title.
export function useAdminRouteTitle(): (route: AdminRouteEntry) => string {
  const labels = useAdminNavLabels();
  return useCallback(
    (route: AdminRouteEntry) => {
      const navId = NAV_ID_BY_PATH[route.path];
      return navId ? labels[navId] : route.title;
    },
    [labels]
  );
}
