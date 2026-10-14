/**
 * Service layer for MCP (Model Context Protocol) related API calls
 */

import { parseErrorDetail } from "@/lib/fetcher";
import {
  MCPOAuthDiscovery,
  MCPServer,
  MCPServerCreateRequest,
  MCPServerUpdateRequest,
  MCPServerStatus,
  MCPAuthenticationType,
  MCPAuthenticationPerformer,
  MCPOAuthProviderMode,
  MCPTransportType,
  MCPAuthTemplate,
} from "@/lib/mcp/types";
import type { ApiResponse, ToolSnapshot } from "@/lib/tools/types";
import {
  updateToolsStatus,
  type ToolStatusUpdateResponse,
} from "@/lib/tools/svc";

/**
 * Delete an MCP server
 */
export async function deleteMCPServer(serverId: number): Promise<void> {
  const response = await fetch(`/api/admin/mcp/server/${serverId}`, {
    method: "DELETE",
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(errorText || "Failed to delete MCP server");
  }
}

/**
 * This performs actual discovery from the MCP server and syncs to DB
 */
export async function refreshMCPServerTools(
  serverId: number
): Promise<ToolSnapshot[]> {
  // Discovers tools from MCP server, upserts to DB, and returns ToolSnapshot format
  const response = await fetch(
    `/api/admin/mcp/server/${serverId}/tools/snapshots?source=mcp`
  );
  if (!response.ok) {
    throw new Error(await parseErrorDetail(response, "Failed to load tools"));
  }

  return await response.json();
}

/**
 * Disable all tools for a specific MCP server
 */
export async function disableAllServerTools(
  toolIds: number[]
): Promise<ToolStatusUpdateResponse> {
  return updateToolsStatus(toolIds, false);
}

/**
 * Create a new MCP server with basic information
 */
export async function createMCPServer(
  data: MCPServerCreateRequest
): Promise<MCPServer> {
  const response = await fetch("/api/admin/mcp/server", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(data),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(errorText || "Failed to create MCP server");
  }

  return await response.json();
}

/**
 * Update an existing MCP server
 */
export async function updateMCPServer(
  serverId: number,
  data: MCPServerUpdateRequest
): Promise<MCPServer> {
  const response = await fetch(`/api/admin/mcp/server/${serverId}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(data),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(errorText || "Failed to update MCP server");
  }

  return await response.json();
}

/**
 * Update the status of an MCP server
 */
export async function updateMCPServerStatus(
  serverId: number,
  status: MCPServerStatus
): Promise<void> {
  const response = await fetch(
    `/api/admin/mcp/server/${serverId}/status?status=${status}`,
    {
      method: "PATCH",
    }
  );

  if (!response.ok) {
    throw new Error(
      await parseErrorDetail(response, "Failed to update MCP server status")
    );
  }
}

interface UpsertMCPServerResponse {
  server_id: number;
  server_name: string;
  server_url: string;
  auth_type: string;
  auth_performer: string;
  oauth_provider_mode?: MCPOAuthProviderMode;
  oauth_authorization_endpoint?: string;
  oauth_token_endpoint?: string;
  oauth_scopes_override?: string[];
  oauth_additional_auth_params?: Record<string, string>;
  no_user_authentication_required: boolean;
}

export async function upsertMCPServer(serverData: {
  name: string;
  description?: string;
  server_url: string;
  transport: string;
  auth_type: MCPAuthenticationType;
  auth_performer: MCPAuthenticationPerformer;
  api_token?: string;
  api_token_changed?: boolean;
  oauth_client_id?: string;
  oauth_client_secret?: string;
  oauth_provider_mode?: MCPOAuthProviderMode;
  oauth_authorization_endpoint?: string;
  oauth_token_endpoint?: string;
  oauth_scopes_override?: string[];
  oauth_additional_auth_params?: Record<string, string>;
  // Mirrors the LLM-provider `api_key_changed` pattern: explicitly signal
  // whether the OAuth credential fields were edited so the backend doesn't
  // overwrite stored values with masked placeholders on resubmit.
  oauth_client_id_changed?: boolean;
  oauth_client_secret_changed?: boolean;
  auth_template?: MCPAuthTemplate;
  auth_template_headers_changed?: Record<string, boolean>;
  admin_credentials?: Record<string, string>;
  // Per-key analogue of `oauth_client_*_changed` for `admin_credentials`.
  admin_credentials_changed?: Record<string, boolean>;
  existing_server_id?: number;
}): Promise<ApiResponse<UpsertMCPServerResponse>> {
  try {
    const response = await fetch("/api/admin/mcp/servers/create", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(serverData),
    });

    if (!response.ok) {
      return {
        data: null,
        error: await parseErrorDetail(
          response,
          "Failed to save MCP server settings"
        ),
      };
    }

    const result: UpsertMCPServerResponse = await response.json();
    return { data: result, error: null };
  } catch (error) {
    return {
      data: null,
      error:
        error instanceof Error
          ? error.message
          : "Failed to save MCP server settings",
    };
  }
}

// ── User-side connect flows (shared by chat and the Craft Apps page) ────────

export type MCPUserOAuthStartResponse =
  | {
      status: "authorization_required";
      server_id: number;
      authorization_url: string;
      redirect_url: string;
    }
  | {
      status: "already_authenticated";
      server_id: number;
      authorization_url: null;
      redirect_url: string;
    };

export function getMCPUserOAuthNavigationUrl(
  response: MCPUserOAuthStartResponse
): string {
  return response.status === "authorization_required"
    ? response.authorization_url
    : response.redirect_url;
}

export type MCPOAuthFailureReason =
  | "client_registration_failed"
  | "discovery_failed"
  | "connection_failed"
  | "oauth_failed";

export class MCPOAuthError extends Error {
  constructor(
    message: string,
    readonly reason: MCPOAuthFailureReason
  ) {
    super(message);
  }
}

async function readMCPOAuthError(response: Response): Promise<Error> {
  const fallback =
    "Could not start OAuth sign-in. Check the server settings and try again.";
  const body: unknown = await response.json().catch(() => null);
  if (!body || typeof body !== "object")
    return new MCPOAuthError(fallback, "oauth_failed");
  const detail =
    "detail" in body &&
    typeof body.detail === "string" &&
    !/<(?:!doctype|html|head|body)[\s>]/i.test(body.detail)
      ? body.detail
      : fallback;
  const reason = "oauth_error" in body ? body.oauth_error : undefined;
  if (
    reason === "client_registration_failed" ||
    reason === "discovery_failed" ||
    reason === "connection_failed" ||
    reason === "oauth_failed"
  ) {
    return new MCPOAuthError(detail, reason);
  }
  return new Error(detail);
}

export async function discoverMCPOAuth(
  serverId: number
): Promise<MCPOAuthDiscovery> {
  const response = await fetch("/api/admin/mcp/oauth/discover", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ server_id: serverId }),
  });
  if (!response.ok) throw new Error("Could not check OAuth setup support");
  return response.json();
}

export async function startMCPAdminOAuth(
  serverId: number,
  returnPath: string,
  options: {
    oauth_client_id?: string;
    oauth_client_secret?: string;
    oauth_client_id_changed?: boolean;
    oauth_client_secret_changed?: boolean;
  } = {}
): Promise<MCPUserOAuthStartResponse> {
  const response = await fetch("/api/admin/mcp/oauth/connect", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      server_id: serverId,
      return_path: returnPath,
      include_resource_param: true,
      ...options,
    }),
  });
  if (!response.ok) {
    throw await readMCPOAuthError(response);
  }
  return response.json();
}

/** Start OAuth or return the internal destination when already authenticated. */
export async function startMCPUserOAuth(
  serverId: number,
  returnPath: string,
  options: { forceReauthentication?: boolean } = {}
): Promise<MCPUserOAuthStartResponse> {
  const res = await fetch("/api/mcp/oauth/connect", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      server_id: serverId,
      return_path: returnPath,
      include_resource_param: true,
      force_reauthentication: options.forceReauthentication ?? false,
    }),
  });
  if (!res.ok) {
    throw await readMCPOAuthError(res);
  }
  return res.json();
}

export interface MCPOAuthCallbackResponse {
  success: boolean;
  server_id: number;
  server_name: string;
  message: string;
  redirect_url: string;
}

/** Complete the OAuth flow started by `startMCPUserOAuth`: exchange the
 * provider's authorization code for tokens and store them for the current
 * user. The code + state are single-use — call at most once per callback. */
export async function completeMCPUserOAuth(
  code: string,
  state: string
): Promise<MCPOAuthCallbackResponse> {
  const params = new URLSearchParams({ code, state });
  const res = await fetch(`/api/mcp/oauth/callback?${params.toString()}`, {
    method: "POST",
  });
  if (!res.ok) {
    throw new Error(
      await parseErrorDetail(res, "Failed to complete authorization")
    );
  }
  return res.json();
}

/** Save per-user credentials (API key / template fields) for an MCP server. */
export async function saveMCPUserCredentials(
  serverId: number,
  credentials: Record<string, string>,
  transport: MCPTransportType = MCPTransportType.STREAMABLE_HTTP
): Promise<void> {
  const res = await fetch("/api/mcp/user-credentials", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      server_id: serverId,
      credentials,
      transport,
    }),
  });
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res, "Failed to save credentials"));
  }
}

/** Disconnect the current user from an MCP server (removes their own
 * credentials; admin-managed configuration is untouched). */
export async function disconnectMCPServer(serverId: number): Promise<void> {
  const res = await fetch(`/api/mcp/user-credentials/${serverId}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res, "Failed to disconnect"));
  }
}
