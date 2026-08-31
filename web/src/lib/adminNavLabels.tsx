"use client";

import { useCallback, useMemo } from "react";
import { useTranslations } from "next-intl";
import type { AdminRouteEntry } from "@/lib/admin-routes";
import {
  getAdminHiddenRouteId,
  getAdminNavId,
  type AdminHiddenRouteId,
  type AdminNavItemId,
} from "@/lib/admin-sidebar-utils";

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

function useAdminHiddenRouteTitles(): Record<AdminHiddenRouteId, string> {
  const t = useTranslations("sidebar");
  return useMemo<Record<AdminHiddenRouteId, string>>(
    () => ({
      documentExplorer: t("adminNav.hiddenRoutes.documentExplorer.title"),
      documentFeedback: t("adminNav.hiddenRoutes.documentFeedback.title"),
      documentProcessing: t("adminNav.hiddenRoutes.documentProcessing.title"),
      oauthTest: t("adminNav.hiddenRoutes.oauthTest.title"),
      standardAnswers: t("adminNav.hiddenRoutes.standardAnswers.title"),
    }),
    [t]
  );
}

// Page headers reuse the sidebar's translated labels so both stay in sync
// across locales. Pages outside the sidebar carry their own title keys.
// Section stubs without a title of their own fall back to the raw title.
export function useAdminRouteTitle(): (route: AdminRouteEntry) => string {
  const labels = useAdminNavLabels();
  const hiddenTitles = useAdminHiddenRouteTitles();
  return useCallback(
    (route: AdminRouteEntry) => {
      const navId = getAdminNavId(route);
      if (navId) return labels[navId];
      const hiddenId = getAdminHiddenRouteId(route);
      return hiddenId ? hiddenTitles[hiddenId] : route.title;
    },
    [labels, hiddenTitles]
  );
}
