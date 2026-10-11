"use client";

import { type ReactNode, useState } from "react";
import { useTranslations } from "next-intl";
import { ContentAction } from "@opal/layouts";
import { Button, Card, Tag, Text } from "@opal/components";
import { SvgCheckCircle, SvgPlug } from "@opal/icons";
import { IconLoader } from "@opal/loaders";
import type { PermSyncMcpServerConfig } from "@/lib/connectors/AutoSyncOptionFields";
import { useAdminMcpServers } from "@/lib/mcp/hooks";
import { upsertMCPServer, type UpsertMCPServerResponse } from "@/lib/mcp/svc";
import {
  MCPAuthenticationPerformer,
  MCPAuthenticationType,
  MCPOAuthProviderMode,
  MCPTransportType,
  type MCPServer,
} from "@/lib/mcp/types";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import type { ApiResponse } from "@/lib/tools/types";
import { Permission } from "@/lib/types";

/** A registered server the censor accepts: same host, and a grant that
 * belongs to each user rather than to the admin. */
export function findPerUserMcpServer(
  servers: MCPServer[],
  host: string
): MCPServer | undefined {
  return servers.find((server) => {
    try {
      return (
        new URL(server.server_url).hostname === host &&
        server.auth_type === MCPAuthenticationType.OAUTH &&
        server.auth_performer === MCPAuthenticationPerformer.PER_USER
      );
    } catch {
      return false;
    }
  });
}

interface PermSyncMcpServerCardProps {
  config: PermSyncMcpServerConfig;
}

/** Registers the source's per-user MCP server from the connector form, so
 * permission sync needs no trip to the MCP Actions page. Users connect their
 * own account later from an assistant that includes the server. */
export default function PermSyncMcpServerCard({
  config,
}: PermSyncMcpServerCardProps) {
  const t = useTranslations(
    "admin.connectorsList.settings.documentAccess.sync.mcpServer"
  );
  // Both the listing and the registration need the global action permission;
  // a scoped manager would see only their own servers and register a second.
  const { isGlobalHolder } = usePermissionAuthority(Permission.MANAGE_ACTIONS);
  const {
    mcpData,
    isLoading,
    error: listError,
    mutateMcpServers,
  } = useAdminMcpServers();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const host: string = new URL(config.url).hostname;
  const server: MCPServer | undefined = findPerUserMcpServer(
    mcpData?.mcp_servers ?? [],
    host
  );
  const canRegister: boolean = isGlobalHolder && listError === undefined;

  async function register() {
    setBusy(true);
    setError(null);
    try {
      const result: ApiResponse<UpsertMCPServerResponse> =
        await upsertMCPServer({
          name: config.name,
          server_url: config.url,
          transport: MCPTransportType.STREAMABLE_HTTP,
          auth_type: MCPAuthenticationType.OAUTH,
          auth_performer: MCPAuthenticationPerformer.PER_USER,
          oauth_provider_mode: MCPOAuthProviderMode.AUTO_DISCOVERY,
        });
      if (result.error !== null) {
        setError(result.error);
      }
      await mutateMcpServers();
    } finally {
      setBusy(false);
    }
  }

  if (isLoading) {
    return (
      <Card border="solid" rounding={4} padding={4}>
        <IconLoader />
      </Card>
    );
  }

  let description: string;
  let action: ReactNode = null;
  if (server === undefined) {
    description = t("unregistered.description", {
      name: config.name,
      url: config.url,
    });
    if (canRegister) {
      action = (
        <Button disabled={busy} onClick={register}>
          {t("register.label")}
        </Button>
      );
    }
  } else {
    description = t("registered.description", { name: server.name });
    action = (
      <Tag title={t("registered.label")} color="green" icon={SvgCheckCircle} />
    );
  }

  return (
    <Card border="solid" rounding={4} padding={4}>
      <ContentAction
        icon={server === undefined ? SvgPlug : SvgCheckCircle}
        title={t("title", { name: config.name })}
        description={description}
        sizePreset="main-content"
        variant="section"
        center
        padding={0}
        rightChildren={action}
      />
      {error !== null && (
        <Text font="secondary-body" color="status-error-05" as="p">
          {error}
        </Text>
      )}
    </Card>
  );
}
