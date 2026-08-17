"use client";

import { Tag, Text } from "@opal/components";
import useUserExternalApps from "@/hooks/useUserExternalApps";
import { useCraftMcpServers } from "@/lib/tools/hooks";
import { getActionIcon } from "@/lib/tools/mcpUtils";
import { getAppTypeLogo } from "@/app/craft/v1/apps/registry";

interface PreApprovalSummaryProps {
  appIds: number[];
  mcpServerIds: number[];
}

export default function PreApprovalSummary({
  appIds,
  mcpServerIds,
}: PreApprovalSummaryProps) {
  const hasAppIds = appIds.length > 0;
  const hasMcpServerIds = mcpServerIds.length > 0;
  const {
    data: apps,
    error: appsError,
    isLoading: appsLoading,
  } = useUserExternalApps(hasAppIds);
  const {
    data: mcpData,
    error: mcpError,
    isLoading: mcpLoading,
  } = useCraftMcpServers(hasMcpServerIds);
  const appsFailed = hasAppIds && Boolean(appsError);
  const mcpServersFailed = hasMcpServerIds && Boolean(mcpError);

  if (!hasAppIds && !hasMcpServerIds) return null;
  // Wait for names so the tags never flash raw id fallbacks.
  if ((hasAppIds && appsLoading) || (hasMcpServerIds && mcpLoading)) {
    return null;
  }

  const appsById = new Map((apps ?? []).map((app) => [app.id, app]));
  const mcpServersById = new Map(
    (mcpData?.mcp_servers ?? []).map((server) => [server.id, server])
  );

  return (
    <div className="flex flex-col gap-2">
      <Text font="main-ui-action" color="text-03">
        Pre-approved apps and MCP servers
      </Text>
      {(appsFailed || mcpServersFailed) && (
        <Text font="secondary-body" color="status-error-05">
          Some pre-approval details couldn’t load. Refresh to try again.
        </Text>
      )}
      <div className="flex flex-wrap gap-2">
        {appIds.map((id) => {
          const app = appsById.get(id);
          if (!app && appsFailed) return null;

          return (
            <Tag
              key={`app-${id}`}
              icon={app ? getAppTypeLogo(app.app_type) : undefined}
              title={app?.name ?? `App #${id}`}
            />
          );
        })}
        {mcpServerIds.map((id) => {
          const server = mcpServersById.get(id);
          if (!server && mcpServersFailed) return null;

          return (
            <Tag
              key={`mcp-${id}`}
              icon={
                server
                  ? getActionIcon(server.server_url, server.name)
                  : undefined
              }
              title={server?.name ?? `MCP server #${id}`}
            />
          );
        })}
      </div>
    </div>
  );
}
