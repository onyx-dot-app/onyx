"use client";

import { useTranslations } from "next-intl";
import type { BadgeProps } from "@opal/components";
import { SvgBlocks, SvgCodeFile, SvgServer } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import type {
  AdminIntegration,
  IntegrationShape,
} from "@/lib/integrations/types";

export const INTEGRATION_SHAPE_ICONS: Record<
  IntegrationShape,
  IconFunctionComponent
> = {
  mcp_server: SvgServer,
  openapi: SvgCodeFile,
  preset: SvgBlocks,
  custom: SvgBlocks,
};

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
