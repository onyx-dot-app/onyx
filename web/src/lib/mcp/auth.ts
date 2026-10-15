import {
  MCPAuthenticationPerformer,
  MCPAuthenticationType,
  type MCPServer,
} from "@/lib/mcp/types";

export type MCPAuthenticationServer = Pick<
  MCPServer,
  | "id"
  | "name"
  | "auth_type"
  | "auth_performer"
  | "auth_template"
  | "user_can_authenticate"
  | "user_credentials"
  | "transport"
>;

/** Only offer flows that the current user can complete from chat. */
export function canAuthenticateMcpServer(
  server: MCPAuthenticationServer
): boolean {
  if (
    server.auth_performer === MCPAuthenticationPerformer.ADMIN &&
    (server.auth_type === MCPAuthenticationType.OAUTH ||
      server.auth_type === MCPAuthenticationType.API_TOKEN)
  )
    return false;
  return (
    (server.auth_template?.required_fields.length ?? 0) > 0 ||
    (server.auth_performer === MCPAuthenticationPerformer.PER_USER &&
      (server.auth_type === MCPAuthenticationType.OAUTH ||
        server.auth_type === MCPAuthenticationType.API_TOKEN))
  );
}
