"use client";

import { useTranslations } from "next-intl";
import type { BadgeProps } from "@opal/components";
import type { AdminIntegration } from "@/lib/integrations/types";

export interface IntegrationLabels {
  shape: (integration: AdminIntegration) => string;
  signIn: (integration: AdminIntegration) => string;
  access: (integration: AdminIntegration) => string;
  status: (
    integration: AdminIntegration
  ) => Pick<BadgeProps, "title" | "color" | "tooltip">;
}

/** Shared text for the list, the plugin page and the Overview tab. */
export function useIntegrationLabels(): IntegrationLabels {
  const t = useTranslations("admin.integrations");
  return {
    shape: (integration) => t(`shape.${integration.shape}`),
    signIn: (integration) =>
      t("signInSummary", {
        mode: integration.auth_mode,
        method: integration.auth_method ?? "none",
      }),
    access: (integration) => {
      const [first] = integration.plugins;
      if (!first) return t("access.none");
      if (integration.plugins.length > 1)
        return t("access.many", { count: integration.plugins.length });
      return first.scope === "organization"
        ? t("access.organization", { plugin: first.plugin_name })
        : t("access.personal", {
            plugin: first.plugin_name,
            owner: first.owner_email ?? "",
          });
    },
    status: (integration) => {
      if (integration.needs_setup)
        return {
          title: t("status.needsSetup"),
          color: "warning",
          tooltip: integration.setup_reason ?? undefined,
        };
      if (!integration.enabled)
        return { title: t("status.off"), color: "default" };
      const state = integration.organization_status?.state;
      if (state === "needs_reconnect")
        return {
          title: t("status.needsReconnect"),
          color: "warning",
          tooltip: integration.organization_status?.reason ?? undefined,
        };
      if (integration.organization_status?.moving_credentials)
        return { title: t("status.movingCredentials"), color: "info" };
      return { title: t("status.ready"), color: "success" };
    },
  };
}
