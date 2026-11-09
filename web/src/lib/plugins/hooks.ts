"use client";

import { useMemo } from "react";
import useOpenApiTools from "@/hooks/useOpenApiTools";
import useSWR from "swr";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Permission } from "@/lib/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";
import type { ExternalAppAdminResponse } from "@/app/craft/v1/apps/registry";
import { useAdminMcpServers } from "@/lib/mcp/hooks";
import type { InstalledPlugin } from "@/lib/plugins/types";
import { useSettings } from "@/lib/settings/hooks";

export function useInstalledPlugins() {
  const mcp = useAdminMcpServers();
  const openapi = useOpenApiTools();
  const { isGlobalHolder } = usePermissionAuthority(
    Permission.FULL_ADMIN_PANEL_ACCESS
  );
  const settings = useSettings();
  const canManageApps =
    isGlobalHolder && settings.onyx_craft_available === true;
  const apps = useSWR<ExternalAppAdminResponse[]>(
    canManageApps ? SWR_KEYS.buildExternalAppsAdmin : null,
    errorHandlingFetcher
  );

  const plugins = useMemo<InstalledPlugin[]>(
    () => [
      ...(mcp.mcpData?.mcp_servers ?? []).map((server) => ({
        kind: "mcp" as const,
        server,
      })),
      ...(openapi.openApiTools ?? []).map((tool) => ({
        kind: "openapi" as const,
        tool,
      })),
      ...(canManageApps ? (apps.data ?? []) : []).map((app) => ({
        kind: "external-app" as const,
        app,
      })),
    ],
    [mcp.mcpData, openapi.openApiTools, apps.data, canManageApps]
  );

  return {
    plugins,
    externalApps: {
      isLoading: canManageApps && apps.isLoading,
      hasError: canManageApps && Boolean(apps.error),
      refresh: apps.mutate,
    },
    mcp: {
      isLoading: mcp.isLoading,
      hasError: Boolean(mcp.error),
      refresh: mcp.mutateMcpServers,
    },
    openapi: {
      isLoading: openapi.isLoading,
      hasError: Boolean(openapi.error),
      refresh: openapi.mutateOpenApiTools,
    },
  };
}
