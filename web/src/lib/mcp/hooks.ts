"use client";

import useSWR, { mutate } from "swr";
import { useMemo, useState } from "react";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";
import type {
  AgentEditorMCPServer,
  MCPAuthenticationServer,
  MCPServersResponse,
} from "@/lib/mcp/types";
import { MCPAuthenticationType, MCPConnectionStatus } from "@/lib/mcp/types";
import { getMcpAuthenticationFlow } from "@/lib/mcp/auth";
import {
  getMCPUserOAuthNavigationUrl,
  saveMCPUserCredentials,
  startMCPUserOAuth,
} from "@/lib/mcp/svc";

/**
 * Every MCP server the current user can reach.
 *
 * This is the user-facing listing. For the admin console's view of every
 * configured server, including ones this user cannot use, see
 * {@link useAdminMcpServers} — the two return the same shape from different
 * endpoints, so picking the wrong one type-checks and silently answers a
 * different question.
 */
export function useMcpServers() {
  const {
    data: mcpData,
    error,
    isLoading,
    mutate: mutateMcpServers,
  } = useSWR<MCPServersResponse>(SWR_KEYS.mcpServers, errorHandlingFetcher);

  return {
    mcpData: mcpData ?? null,
    isLoading,
    error,
    mutateMcpServers,
  };
}

/**
 * Every configured MCP server, from the admin endpoint. Use this only on admin
 * surfaces; {@link useMcpServers} is what user-facing UI should read.
 */
export function useAdminMcpServers() {
  const {
    data: mcpData,
    error,
    isLoading,
    mutate: mutateMcpServers,
  } = useSWR<MCPServersResponse>(
    SWR_KEYS.adminMcpServers,
    errorHandlingFetcher
  );

  return {
    mcpData: mcpData ?? null,
    isLoading,
    error,
    mutateMcpServers,
  };
}

/**
 * The MCP servers relevant to one agent: those the user can reach, plus any
 * already attached to the agent that they cannot. `can_attach` distinguishes
 * them, so the editor can show an attached server without offering it as a
 * choice the user is not allowed to make.
 */
export function useMcpServersForAgent(agentId: number | undefined) {
  const accessible = useMcpServers();
  const {
    data: attachedData,
    error: attachedError,
    isLoading: attachedIsLoading,
  } = useSWR<MCPServersResponse>(
    agentId ? SWR_KEYS.agentMcpServers(agentId) : null,
    errorHandlingFetcher
  );

  const mcpServers = useMemo<AgentEditorMCPServer[]>(() => {
    const accessibleServers = accessible.mcpData?.mcp_servers ?? [];
    const accessibleIds = new Set(accessibleServers.map((server) => server.id));
    return [
      ...accessibleServers.map((server) => ({ ...server, can_attach: true })),
      ...(attachedData?.mcp_servers ?? [])
        .filter((server) => !accessibleIds.has(server.id))
        .map((server) => ({ ...server, can_attach: false })),
    ];
  }, [accessible.mcpData, attachedData]);

  return {
    mcpServers,
    isLoading:
      accessible.isLoading || (agentId !== undefined && attachedIsLoading),
    error: accessible.error || attachedError,
  };
}

/**
 * MCP servers an admin made available to Craft, with this user's connection
 * state (`craft_connected`).
 */
export function useCraftMcpServers(enabled: boolean = true) {
  const { data, error, isLoading } = useSWR<MCPServersResponse>(
    enabled ? SWR_KEYS.mcpServersCraft : null,
    errorHandlingFetcher,
    // The Apps page re-reads this after every connect/disconnect; holding the
    // previous list keeps the tab from flashing empty on revalidation.
    { keepPreviousData: true }
  );

  const refresh = () => mutate(SWR_KEYS.mcpServersCraft);

  return { data, error, isLoading, refresh };
}

interface MCPCredentialRequest {
  server: MCPAuthenticationServer;
  forceReauthentication: boolean;
}

export function useMcpAuthentication(
  agentId: number | undefined,
  enabled = true
) {
  const {
    data,
    error,
    isLoading,
    mutate: refresh,
  } = useSWR<MCPServersResponse>(
    enabled && agentId !== undefined ? SWR_KEYS.agentMcpServers(agentId) : null,
    errorHandlingFetcher
  );
  const [loadingServerId, setLoadingServerId] = useState<number | null>(null);
  const [authenticationError, setAuthenticationError] = useState<Error | null>(
    null
  );
  const [credentialRequest, setCredentialRequest] =
    useState<MCPCredentialRequest | null>(null);

  async function startOAuth(
    server: MCPAuthenticationServer,
    forceReauthentication: boolean
  ) {
    setLoadingServerId(server.id);
    try {
      const result = await startMCPUserOAuth(
        server.id,
        window.location.pathname + window.location.search,
        { forceReauthentication }
      );
      window.location.href = getMCPUserOAuthNavigationUrl(result);
    } catch (error) {
      setLoadingServerId(null);
      throw error;
    }
  }

  async function authenticate(
    server: MCPAuthenticationServer,
    forceReauthentication = server.connection_status ===
      MCPConnectionStatus.REAUTH_REQUIRED
  ) {
    if (loadingServerId !== null) return;
    const flow = getMcpAuthenticationFlow(server);
    if (!flow) return;
    setAuthenticationError(null);
    if (flow === "credentials") {
      setCredentialRequest({ server, forceReauthentication });
      return;
    }
    try {
      await startOAuth(server, forceReauthentication);
    } catch (error) {
      setAuthenticationError(
        error instanceof Error ? error : new Error(String(error))
      );
    }
  }

  function cancelCredentialRequest() {
    setCredentialRequest(null);
  }

  async function submitCredentials(credentials: Record<string, string>) {
    if (!credentialRequest) return;
    const { server, forceReauthentication } = credentialRequest;
    await saveMCPUserCredentials(server.id, credentials, server.transport);
    if (server.auth_type === MCPAuthenticationType.OAUTH) {
      await startOAuth(server, forceReauthentication);
    } else {
      await refresh();
    }
    setCredentialRequest(null);
  }

  return {
    servers: data?.mcp_servers ?? [],
    error,
    isLoading,
    refresh,
    authenticate,
    loadingServerId,
    authenticationError,
    credentialRequest,
    cancelCredentialRequest,
    submitCredentials,
  };
}
