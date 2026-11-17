/**
 * Service layer for MCP (Model Context Protocol) related API calls
 */

import { parseErrorDetail } from "@/lib/fetcher";
import * as yup from "yup";
import type {
  MCPProbeProgress,
  MCPUserPreferences,
  MCPUserPreferencesRequest,
} from "@/lib/mcp/types";
import {
  MCPOAuthDiscovery,
  MCPTransportType,
  MCPSetupProbeResult,
} from "@/lib/mcp/types";

export async function updateMCPUserPreferences(
  serverId: number,
  preferences: MCPUserPreferencesRequest
): Promise<MCPUserPreferences> {
  const response = await fetch(`/api/mcp/server/${serverId}/preferences`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(preferences),
  });
  if (!response.ok) {
    throw new Error(
      await parseErrorDetail(response, "Failed to save MCP preferences")
    );
  }
  return yup
    .object({
      enabled_in_chat: yup.boolean().defined(),
      enabled_in_craft: yup.boolean().defined(),
    })
    .validateSync(await response.json(), { strict: true });
}

const probeTransport = yup
  .mixed<MCPTransportType.STREAMABLE_HTTP | MCPTransportType.SSE>()
  .oneOf([MCPTransportType.STREAMABLE_HTTP, MCPTransportType.SSE])
  .defined();
const progressSchema = yup.object({
  type: yup.mixed<"progress">().oneOf(["progress"]).defined(),
  stage: yup
    .mixed<MCPProbeProgress["stage"]>()
    .oneOf(["contacting_server", "authentication"])
    .defined(),
  state: yup
    .mixed<MCPProbeProgress["state"]>()
    .oneOf(["pending", "success", "error"])
    .defined(),
});
// oxlint-disable-next-line anti-slop/no-unknown-parameters -- Validates untrusted probe JSON at the stream boundary.
function parseProbeResult(value: unknown): MCPSetupProbeResult {
  const { kind } = yup
    .object({ kind: yup.string().defined() })
    .validateSync(value, { strict: true });
  switch (kind) {
    case "public":
      return yup
        .object({
          kind: yup.mixed<"public">().oneOf(["public"]).defined(),
          transport: probeTransport,
          tool_count: yup.number().integer().min(0).defined(),
          server_name: yup.string().defined(),
        })
        .validateSync(value, { strict: true });
    case "oauth":
      return yup
        .object({
          kind: yup.mixed<"oauth">().oneOf(["oauth"]).defined(),
          transport: probeTransport.nullable(),
          discovery: yup
            .object({
              status: yup
                .mixed<MCPOAuthDiscovery["status"]>()
                .oneOf(["metadata_found", "metadata_missing", "unreachable"])
                .defined(),
              supports_automatic_registration: yup
                .boolean()
                .nullable()
                .defined(),
              supports_client_metadata: yup.boolean().nullable().defined(),
              authorization_endpoint: yup.string().nullable().defined(),
              token_endpoint: yup.string().nullable().defined(),
            })
            .defined(),
        })
        .validateSync(value, { strict: true });
    case "auth_unknown":
      return yup
        .object({
          kind: yup.mixed<"auth_unknown">().oneOf(["auth_unknown"]).defined(),
          transport: probeTransport.nullable(),
        })
        .validateSync(value, { strict: true });
    case "unreachable":
      return yup
        .object({
          kind: yup.mixed<"unreachable">().oneOf(["unreachable"]).defined(),
          reason: yup
            .mixed<"blocked" | "connection_failed">()
            .oneOf(["blocked", "connection_failed"])
            .defined(),
        })
        .validateSync(value, { strict: true });
    default:
      throw new Error("Invalid MCP probe result");
  }
}

export async function streamMCPServerProbe(
  serverUrl: string,
  onProgress: (event: MCPProbeProgress) => void,
  signal?: AbortSignal
): Promise<MCPSetupProbeResult> {
  const response = await fetch("/api/admin/mcp/probe", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ server_url: serverUrl }),
    signal,
  });
  if (!response.ok || !response.body) throw new Error("MCP probe failed");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: MCPSetupProbeResult | undefined;
  function consume(line: string) {
    if (!line.trim()) return;
    const value: unknown = JSON.parse(line);
    const event = yup
      .object({
        type: yup
          .mixed<"progress" | "result">()
          .oneOf(["progress", "result"])
          .defined(),
      })
      .validateSync(value, { strict: true });
    if (result) throw new Error("Unexpected MCP probe event");
    if (event.type === "progress")
      onProgress(progressSchema.validateSync(value, { strict: true }));
    else
      result = parseProbeResult(
        yup
          .object({ result: yup.mixed().defined() })
          .validateSync(value, { strict: true }).result
      );
  }
  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      if (buffer.length > 65536) throw new Error("Invalid MCP probe stream");
      let newline: number;
      while ((newline = buffer.indexOf("\n")) !== -1) {
        consume(buffer.slice(0, newline));
        buffer = buffer.slice(newline + 1);
      }
      if (done) break;
    }
    consume(buffer);
    if (!result) throw new Error("Incomplete MCP probe stream");
    return result;
  } finally {
    await reader.cancel();
    reader.releaseLock();
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

export type MCPOAuthFailureReason =
  | "client_registration_failed"
  | "client_metadata_rejected"
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

async function readMCPOAuthError(
  response: Response,
  fallbackReason: "connection_failed" | "oauth_failed" = "oauth_failed"
): Promise<Error> {
  const fallback =
    fallbackReason === "connection_failed"
      ? "Could not connect to the MCP server. Check the server settings and try again."
      : "Could not start OAuth sign-in. Check the server settings and try again.";
  const body: unknown = await response.json().catch(() => null);
  if (!body || typeof body !== "object")
    return new MCPOAuthError(fallback, fallbackReason);
  const detail =
    "detail" in body &&
    typeof body.detail === "string" &&
    !/<(?:!doctype|html|head|body)[\s>]/i.test(body.detail)
      ? body.detail
      : fallback;
  const reason = "oauth_error" in body ? body.oauth_error : undefined;
  if (
    reason === "client_registration_failed" ||
    reason === "client_metadata_rejected" ||
    reason === "discovery_failed" ||
    reason === "connection_failed" ||
    reason === "oauth_failed"
  ) {
    return new MCPOAuthError(detail, reason);
  }
  return detail === fallback
    ? new MCPOAuthError(fallback, fallbackReason)
    : new Error(detail);
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
