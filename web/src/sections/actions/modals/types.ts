import type {
  MCPTransportType,
  MCPAuthenticationType,
  MCPAuthenticationPerformer,
  MCPAuthTemplate,
  MCPOAuthProviderMode,
} from "@/lib/mcp/types";

export interface MCPAuthFormValues {
  transport: MCPTransportType;
  auth_type: MCPAuthenticationType;
  auth_performer: MCPAuthenticationPerformer;
  api_token: string;
  auth_template: MCPAuthTemplate;
  user_credentials: Record<string, string>;
  oauth_setup_mode: "automatic" | "own_client";
  oauth_client_id: string;
  oauth_client_secret: string;
  oauth_provider_mode: MCPOAuthProviderMode;
  oauth_cimd_enabled: boolean;
  oauth_authorization_endpoint: string;
  oauth_token_endpoint: string;
  oauth_scopes_override: string;
  oauth_additional_auth_params: string;
}
