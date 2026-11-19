"use client";

import { useTranslations } from "next-intl";
import type { BadgeProps } from "@opal/components";
import type { AdminIntegration } from "@/lib/integrations/types";

export function useIntegrationLabels() {
  const t = useTranslations("admin.integrations");
  return {
    shape: (integration: Pick<AdminIntegration, "shape">) =>
      t(`shape.${integration.shape}`),
    signIn: (
      integration: Pick<AdminIntegration, "auth_mode" | "auth_method">
    ) =>
      t("signInSummary", {
        mode: integration.auth_mode,
        method: integration.auth_method ?? "none",
      }),
    access: (integration: AdminIntegration) => {
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
    status: (
      integration: AdminIntegration
    ): Pick<BadgeProps, "title" | "color" | "tooltip"> => {
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
      return { title: t("status.ready"), color: "success" };
    },
  };
}
