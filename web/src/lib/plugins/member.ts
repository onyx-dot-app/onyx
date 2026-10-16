"use client";

import useSWR, { mutate, useSWRConfig, type ScopedMutator } from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import {
  MCPAuthenticationPerformer,
  MCPAuthenticationType,
  MCPConnectionStatus,
  type MCPServer,
  type MCPServersResponse,
  type MCPUserPreferencesRequest,
} from "@/lib/mcp/types";
import { getMcpAuthenticationFlow } from "@/lib/mcp/auth";
import {
  disconnectMCPServer,
  saveMCPUserCredentials,
  startMCPUserOAuth,
  updateMCPUserPreferences,
} from "@/lib/mcp/svc";
import { getOAuthAuthorizationUrl } from "@/lib/oauth/api";
import type { PluginReference } from "@/lib/plugins/types";
import {
  MemberPluginConnectionError,
  runMemberPluginOAuth,
  type MemberPluginConnectOptions,
} from "@/lib/plugins/memberConnection";
import { SWR_KEYS } from "@/lib/swr-keys";
import type {
  OAuthTokenStatus,
  ToolSnapshot,
  ToolUserPreferencesRequest,
} from "@/lib/tools/types";
import { updateToolUserPreferences } from "@/lib/tools/svc";
import type { ExternalAppUserResponse } from "@/app/craft/v1/apps/registry";
import {
  disconnectUserFromApp,
  startExternalAppOAuth,
  upsertUserCredentials,
} from "@/app/craft/services/externalAppsService";
import { useSettings } from "@/lib/settings/hooks";

export { MemberPluginConnectionError } from "@/lib/plugins/memberConnection";

export type MemberPluginConnection =
  | {
      kind: "connected";
      ownership: "user" | "workspace" | "session" | "none";
    }
  | { kind: "oauth" }
  | { kind: "credentials"; fields: string[]; thenOAuth: boolean }
  | { kind: "unconfigured" }
  | { kind: "checking" }
  | { kind: "unavailable" };

export type MemberPlugin =
  | {
      kind: "external-app";
      app: ExternalAppUserResponse;
      connection: MemberPluginConnection;
    }
  | {
      kind: "mcp";
      server: MCPServer;
      tools: ToolSnapshot[];
      connection: MemberPluginConnection;
    }
  | {
      kind: "openapi";
      tool: ToolSnapshot;
      connection: MemberPluginConnection;
    };

export interface MemberPluginErrors {
  apps?: Error;
  servers?: Error;
  tools?: Error;
  oauth?: Error;
}

type OAuthStatus =
  | { kind: "loaded"; tokens: OAuthTokenStatus[] }
  | { kind: "loading" }
  | { kind: "error" };

function mcpConnection(server: MCPServer): MemberPluginConnection {
  const fields = server.auth_template?.required_fields ?? [];
  if (server.connection_status === MCPConnectionStatus.CONNECTED) {
    const ownership =
      server.auth_performer === MCPAuthenticationPerformer.ADMIN &&
      (server.auth_type === MCPAuthenticationType.API_TOKEN ||
        server.auth_type === MCPAuthenticationType.OAUTH)
        ? "workspace"
        : fields.length > 0 ||
            server.auth_type === MCPAuthenticationType.API_TOKEN ||
            server.auth_type === MCPAuthenticationType.OAUTH
          ? "user"
          : server.auth_type === MCPAuthenticationType.PT_OAUTH
            ? "session"
            : "none";
    return { kind: "connected", ownership };
  }
  if (server.connection_status == null) return { kind: "unavailable" };
  const flow = getMcpAuthenticationFlow(server);
  if (flow === "credentials") {
    return {
      kind: "credentials",
      fields: fields.length > 0 ? fields : ["api_key"],
      thenOAuth: server.auth_type === MCPAuthenticationType.OAUTH,
    };
  }
  if (flow === "oauth") return { kind: "oauth" };
  return { kind: "unconfigured" };
}

function openAPIConnection(
  tool: ToolSnapshot,
  oauth: OAuthStatus
): MemberPluginConnection {
  if (tool.oauth_config_id) {
    if (oauth.kind === "loading") return { kind: "checking" };
    if (oauth.kind === "error") return { kind: "unavailable" };
    return oauth.tokens.some(
      (token) =>
        token.oauth_config_id === tool.oauth_config_id && !token.is_expired
    )
      ? { kind: "connected", ownership: "user" }
      : { kind: "oauth" };
  }
  if (tool.passthrough_auth) return { kind: "connected", ownership: "session" };
  return {
    kind: "connected",
    ownership: tool.custom_headers.length > 0 ? "workspace" : "none",
  };
}

export function buildMemberPlugins(
  servers: MCPServer[],
  tools: ToolSnapshot[],
  oauth: OAuthStatus,
  apps: ExternalAppUserResponse[] = []
): MemberPlugin[] {
  const enabledTools = tools.filter((tool) => tool.enabled);
  return [
    ...apps.map(
      (app): MemberPlugin => ({
        kind: "external-app",
        app,
        connection: app.authenticated
          ? {
              kind: "connected",
              ownership:
                app.supports_oauth || app.credential_keys.length > 0
                  ? "user"
                  : "workspace",
            }
          : app.supports_oauth
            ? { kind: "oauth" }
            : app.credential_keys.length > 0
              ? {
                  kind: "credentials",
                  fields: app.credential_keys,
                  thenOAuth: false,
                }
              : { kind: "unconfigured" },
      })
    ),
    ...servers.map(
      (server): MemberPlugin => ({
        kind: "mcp",
        server,
        tools: enabledTools.filter((tool) => tool.mcp_server_id === server.id),
        connection: mcpConnection(server),
      })
    ),
    ...enabledTools
      .filter(
        (tool) =>
          !tool.in_code_tool_id && !tool.mcp_server_id && tool.definition
      )
      .map(
        (tool): MemberPlugin => ({
          kind: "openapi",
          tool,
          connection: openAPIConnection(tool, oauth),
        })
      ),
  ];
}

export function useMemberPlugins({
  agentId,
  surface = "all",
}: { agentId?: number; surface?: "all" | "chat" | "craft" } = {}) {
  const settings = useSettings();
  const appsEnabled =
    surface !== "chat" &&
    agentId === undefined &&
    settings.onyx_craft_enabled === true;
  const { mutate: mutateCache } = useSWRConfig();
  const servers = useSWR<MCPServersResponse, Error>(
    surface === "craft"
      ? SWR_KEYS.mcpServersCraft
      : agentId === undefined
        ? SWR_KEYS.mcpServers
        : SWR_KEYS.agentMcpServers(agentId),
    errorHandlingFetcher
  );
  const tools = useSWR<ToolSnapshot[], Error>(
    surface === "craft" ? null : SWR_KEYS.tools,
    errorHandlingFetcher
  );
  const oauth = useSWR<OAuthTokenStatus[], Error>(
    surface === "craft" ? null : SWR_KEYS.oauthTokenStatus,
    errorHandlingFetcher
  );
  const apps = useSWR<ExternalAppUserResponse[], Error>(
    appsEnabled ? SWR_KEYS.buildExternalApps : null,
    errorHandlingFetcher
  );
  const errors: MemberPluginErrors = {
    apps: apps.error,
    servers: servers.error,
    tools: tools.error,
    oauth: oauth.error,
  };
  return {
    plugins: buildMemberPlugins(
      (servers.data?.mcp_servers ?? []).filter(
        (server) => surface !== "craft" || server.available_in_craft === true
      ),
      tools.data ?? [],
      oauth.error
        ? { kind: "error" }
        : oauth.data
          ? { kind: "loaded", tokens: oauth.data }
          : { kind: "loading" },
      apps.data ?? []
    ),
    loading: {
      apps: apps.isLoading,
      servers: servers.isLoading,
      tools: tools.isLoading,
      oauth: oauth.isLoading,
    },
    isLoading:
      servers.isLoading || tools.isLoading || oauth.isLoading || apps.isLoading,
    errors,
    async refresh(): Promise<void> {
      await refreshMemberPluginCaches(mutateCache);
    },
  };
}

export function memberPluginReference(plugin: MemberPlugin): PluginReference {
  if (plugin.kind === "external-app")
    return { kind: "external-app", id: plugin.app.id };
  return plugin.kind === "mcp"
    ? { kind: "mcp", id: plugin.server.id }
    : { kind: "openapi", id: plugin.tool.id };
}

export function memberPluginName(plugin: MemberPlugin): string {
  if (plugin.kind === "external-app") return plugin.app.name;
  return plugin.kind === "mcp"
    ? plugin.server.name
    : plugin.tool.display_name || plugin.tool.name;
}

export function canUseMemberPlugin(plugin: MemberPlugin): boolean {
  return plugin.connection.kind === "connected";
}

export async function verifyMemberPluginConnection(
  reference: PluginReference
): Promise<void> {
  let plugins: MemberPlugin[];
  if (reference.kind === "external-app") {
    plugins = buildMemberPlugins(
      [],
      [],
      { kind: "loaded", tokens: [] },
      await errorHandlingFetcher<ExternalAppUserResponse[]>(
        SWR_KEYS.buildExternalApps
      )
    );
  } else if (reference.kind === "mcp") {
    const servers = await errorHandlingFetcher<MCPServersResponse>(
      SWR_KEYS.mcpServers
    );
    plugins = buildMemberPlugins(servers.mcp_servers, [], {
      kind: "loaded",
      tokens: [],
    });
  } else {
    const [tools, tokens] = await Promise.all([
      errorHandlingFetcher<ToolSnapshot[]>(SWR_KEYS.tools),
      errorHandlingFetcher<OAuthTokenStatus[]>(SWR_KEYS.oauthTokenStatus),
    ]);
    plugins = buildMemberPlugins([], tools, { kind: "loaded", tokens });
  }
  const plugin = plugins.find((candidate) => {
    const candidateReference = memberPluginReference(candidate);
    return (
      candidateReference.kind === reference.kind &&
      candidateReference.id === reference.id
    );
  });
  if (!plugin || !canUseMemberPlugin(plugin)) {
    throw new MemberPluginConnectionError("not_connected");
  }
}

export async function refreshMemberPluginCaches(
  mutateCache: ScopedMutator = mutate
): Promise<void> {
  await mutateCache(
    (key) =>
      typeof key === "string" &&
      (key === SWR_KEYS.mcpServers ||
        key === SWR_KEYS.buildExternalApps ||
        key === SWR_KEYS.mcpServersCraft ||
        key.startsWith("/api/mcp/servers/persona/") ||
        key === SWR_KEYS.tools ||
        key === SWR_KEYS.oauthTokenStatus ||
        key === SWR_KEYS.agents ||
        /^\/api\/persona\/\d+(?:\?|$)/.test(key))
  );
}

export async function saveMemberMCPPreferences(
  serverId: number,
  preferences: MCPUserPreferencesRequest,
  mutateCache: ScopedMutator
): Promise<void> {
  function updateServers(
    current: MCPServersResponse | undefined,
    values: Partial<MCPUserPreferencesRequest>
  ): MCPServersResponse | undefined {
    if (!current) return current;
    return {
      ...current,
      mcp_servers: current.mcp_servers.map((server) =>
        server.id === serverId
          ? {
              ...server,
              user_enabled_in_chat:
                values.enabled_in_chat ?? server.user_enabled_in_chat ?? true,
              user_enabled_in_craft:
                values.enabled_in_craft ?? server.user_enabled_in_craft ?? true,
            }
          : server
      ),
    };
  }

  const request = updateMCPUserPreferences(serverId, preferences);
  await mutateCache<MCPServersResponse | undefined>(
    (key) =>
      typeof key === "string" &&
      (key === SWR_KEYS.mcpServers ||
        key === SWR_KEYS.mcpServersCraft ||
        key.startsWith("/api/mcp/servers/persona/")),
    async (current) => updateServers(current, await request),
    {
      optimisticData: (current) => updateServers(current, preferences),
      rollbackOnError: true,
      revalidate: false,
      throwOnError: true,
    }
  );
  await request;
  await refreshMemberPluginCaches(mutateCache);
}

export async function saveMemberOpenAPIPreferences(
  toolId: number,
  preferences: ToolUserPreferencesRequest,
  mutateCache: ScopedMutator
): Promise<void> {
  function updateTools(
    current: ToolSnapshot[] | undefined,
    values: ToolUserPreferencesRequest
  ): ToolSnapshot[] | undefined {
    return current?.map((tool) =>
      tool.id === toolId
        ? { ...tool, user_enabled_in_chat: values.enabled_in_chat }
        : tool
    );
  }

  const request = updateToolUserPreferences(toolId, preferences);
  await mutateCache<ToolSnapshot[] | undefined>(
    (key) => key === SWR_KEYS.tools,
    async (current) => updateTools(current, await request),
    {
      optimisticData: (current) => updateTools(current, preferences),
      rollbackOnError: true,
      revalidate: false,
      throwOnError: true,
    }
  );
  await request;
  await refreshMemberPluginCaches(mutateCache);
}

export async function connectMemberPlugin(
  plugin: MemberPlugin,
  credentialValues?: Record<string, string>,
  options: MemberPluginConnectOptions = {}
): Promise<void> {
  const connection = plugin.connection;
  if (connection.kind === "connected") return;
  if (connection.kind !== "oauth" && connection.kind !== "credentials") {
    throw new MemberPluginConnectionError("unconfigured");
  }
  if (connection.kind === "credentials") {
    if (connection.fields.some((field) => !credentialValues?.[field]?.trim())) {
      throw new MemberPluginConnectionError("credentials_required");
    }
  }
  const saveCredentials = async () => {
    if (
      plugin.kind === "external-app" &&
      credentialValues &&
      connection.kind === "credentials"
    ) {
      await upsertUserCredentials(plugin.app.id, credentialValues);
    }
    if (
      plugin.kind === "mcp" &&
      credentialValues &&
      connection.kind === "credentials"
    ) {
      await saveMCPUserCredentials(
        plugin.server.id,
        credentialValues,
        plugin.server.transport
      );
    }
  };
  try {
    if (connection.kind === "oauth" || connection.thenOAuth) {
      await runMemberPluginOAuth(
        memberPluginReference(plugin),
        async (returnPath) => {
          await saveCredentials();
          if (options.signal?.aborted)
            throw new MemberPluginConnectionError("cancelled");
          if (plugin.kind === "mcp") {
            const response = await startMCPUserOAuth(
              plugin.server.id,
              returnPath,
              {
                forceReauthentication:
                  plugin.server.connection_status ===
                  MCPConnectionStatus.REAUTH_REQUIRED,
              }
            );
            return response.status === "authorization_required"
              ? response.authorization_url
              : null;
          }
          if (plugin.kind === "external-app") {
            return (await startExternalAppOAuth(plugin.app.id, returnPath))
              .authorize_url;
          }
          if (!plugin.tool.oauth_config_id)
            throw new MemberPluginConnectionError("unconfigured");
          return getOAuthAuthorizationUrl(
            plugin.tool.oauth_config_id,
            returnPath,
            "request_failed"
          );
        },
        options
      );
    } else {
      if (options.signal?.aborted)
        throw new MemberPluginConnectionError("cancelled");
      await saveCredentials();
    }
    if (options.signal?.aborted)
      throw new MemberPluginConnectionError("cancelled");
    await verifyMemberPluginConnection(memberPluginReference(plugin));
  } finally {
    await refreshMemberPluginCaches();
  }
}

export async function disconnectMemberPlugin(
  plugin: MemberPlugin
): Promise<void> {
  if (
    plugin.connection.kind !== "connected" ||
    plugin.connection.ownership !== "user"
  ) {
    throw new MemberPluginConnectionError("unconfigured");
  }
  if (plugin.kind === "mcp") {
    await disconnectMCPServer(plugin.server.id);
  } else if (plugin.kind === "external-app") {
    await disconnectUserFromApp(plugin.app.id);
  } else {
    if (!plugin.tool.oauth_config_id)
      throw new MemberPluginConnectionError("unconfigured");
    const response = await fetch(
      `/api/oauth-config/${plugin.tool.oauth_config_id}/token`,
      { method: "DELETE" }
    );
    if (!response.ok) throw new MemberPluginConnectionError("request_failed");
  }
  await refreshMemberPluginCaches();
}
