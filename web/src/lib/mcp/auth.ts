import {
  MCPAuthenticationPerformer,
  MCPAuthenticationType,
  type MCPAuthenticationServer,
  type MCPAuthenticationFlow,
} from "@/lib/mcp/types";

/** Only offer flows that the current user can complete from chat. */
export function getMcpAuthenticationFlow(
  server: MCPAuthenticationServer
): MCPAuthenticationFlow | null {
  if (
    server.auth_performer === MCPAuthenticationPerformer.ADMIN &&
    (server.auth_type === MCPAuthenticationType.OAUTH ||
      server.auth_type === MCPAuthenticationType.API_TOKEN)
  )
    return null;
  if ((server.auth_template?.required_fields.length ?? 0) > 0)
    return "credentials";
  if (server.auth_performer !== MCPAuthenticationPerformer.PER_USER)
    return null;
  if (server.auth_type === MCPAuthenticationType.API_TOKEN)
    return "credentials";
  if (server.auth_type === MCPAuthenticationType.OAUTH) return "oauth";
  return null;
}

export function canAuthenticateMcpServer(
  server: MCPAuthenticationServer
): boolean {
  return getMcpAuthenticationFlow(server) !== null;
}
