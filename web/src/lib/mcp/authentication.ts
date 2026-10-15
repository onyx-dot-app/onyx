"use client";

import { useState } from "react";
import { useChatMcpServers } from "@/lib/mcp/hooks";
import {
  canAuthenticateMcpServer,
  type MCPAuthenticationServer,
} from "@/lib/mcp/auth";
import { MCPAuthenticationType } from "@/lib/mcp/types";
import {
  getMCPUserOAuthNavigationUrl,
  saveMCPUserCredentials,
  startMCPUserOAuth,
} from "@/lib/mcp/svc";
import type { MCPUserCredentialsModalProps } from "@/lib/mcp/components/MCPUserCredentialsModal";

export function useMcpAuthentication(
  agentId: number | undefined,
  enabled = true
) {
  const listing = useChatMcpServers(agentId, enabled);
  const [loadingServerId, setLoadingServerId] = useState<number | null>(null);
  const [authenticationError, setAuthenticationError] = useState<Error | null>(
    null
  );
  const [credentialRequest, setCredentialRequest] = useState<{
    server: MCPAuthenticationServer;
    forceReauthentication: boolean;
  } | null>(null);

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
    } finally {
      setLoadingServerId(null);
    }
  }

  async function authenticate(
    server: MCPAuthenticationServer,
    forceReauthentication = false
  ) {
    if (!canAuthenticateMcpServer(server)) return;
    setAuthenticationError(null);
    if (
      (server.auth_template?.required_fields.length ?? 0) > 0 ||
      server.auth_type === MCPAuthenticationType.API_TOKEN
    ) {
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

  const credentialModalProps: MCPUserCredentialsModalProps | null =
    credentialRequest
      ? {
          server: credentialRequest.server,
          onClose: () => setCredentialRequest(null),
          onSubmit: async (credentials) => {
            const { server, forceReauthentication } = credentialRequest;
            await saveMCPUserCredentials(
              server.id,
              credentials,
              server.transport
            );
            if (server.auth_type === MCPAuthenticationType.OAUTH) {
              await startOAuth(server, forceReauthentication);
            } else {
              await listing.refresh();
            }
            setCredentialRequest(null);
          },
        }
      : null;

  return {
    ...listing,
    authenticate,
    loadingServerId,
    authenticationError,
    credentialModalProps,
  };
}
