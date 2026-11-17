export type IntegrationKind = "mcp_server" | "api";
export type IntegrationShape = "mcp_server" | "openapi" | "preset" | "custom";
export type AuthMode = "none" | "shared" | "individual";
export type AuthMethod = "oauth2" | "api_key" | "onyx_login" | "managed";
export type ConnectionState =
  | "connected"
  | "not_connected"
  | "needs_reconnect"
  | "not_set_up";
export type PolicyValue = "allow" | "ask" | "blocked";
export type InstallationPolicy =
  | "REQUIRED"
  | "DEFAULT"
  | "AVAILABLE"
  | "NOT_AVAILABLE";
export type McpTransport = "STREAMABLE_HTTP" | "SSE";
export type OAuthProviderMode = "preset" | "manual" | "discovery";

export interface IntegrationStatus {
  state: ConnectionState;
  reason: string | null;
}

export interface CredentialField {
  key: string;
  label: string;
  secret: boolean;
}

export interface IntegrationPluginRef {
  plugin_id: string;
  plugin_name: string;
  scope: "organization" | "personal";
  owner_email: string | null;
  installation_policy: InstallationPolicy | null;
}

export interface IntegrationAction {
  key: string;
  display_name: string;
  description: string | null;
  read_only: boolean | null;
  default_policy: PolicyValue;
  admin_policy: PolicyValue | null;
  effective_admin_policy: PolicyValue;
  /** Craft asks before each call of this action, so Allow has no effect. */
  always_asks: boolean;
}

export interface AdminIntegration {
  id: number;
  kind: IntegrationKind;
  shape: IntegrationShape;
  name: string;
  description: string | null;
  preset_id: string | null;
  enabled: boolean;
  auth_mode: AuthMode;
  auth_method: AuthMethod | null;
  plugins: IntegrationPluginRef[];
  created_by_email: string | null;
  action_count: number;
  needs_setup: boolean;
  setup_reason: string | null;
  organization_status: IntegrationStatus | null;
  can_manage: boolean;
}

export interface OAuthClientInput {
  provider_mode: OAuthProviderMode;
  authorization_url: string;
  token_url: string;
  scopes: string[] | null;
  additional_params: Record<string, string> | null;
  pkce: boolean | null;
  client_id: string | null;
  client_secret: string | null;
}

export type OAuthClientView = Omit<OAuthClientInput, "client_secret"> & {
  has_client_secret: boolean;
};

export type IntegrationConfig =
  | { shape: "mcp_server"; server_url: string; transport: McpTransport }
  | { shape: "openapi"; openapi_spec: Record<string, unknown> }
  | {
      shape: "preset";
      preset_id: string;
      organization_credentials: Record<string, string> | null;
    }
  | { shape: "custom"; upstream_url_patterns: string[] };

export type IntegrationConfigView =
  | Exclude<IntegrationConfig, { shape: "preset" }>
  | { shape: "preset"; preset_id: string };

export interface AdminIntegrationDetail extends AdminIntegration {
  config: IntegrationConfigView;
  credential_fields: CredentialField[];
  header_template: Record<string, string> | null;
  users_can_save_always_allow: boolean;
  oauth_client: OAuthClientView | null;
  /** False when the user cannot manage it, or when Onyx provides the app. */
  can_delete: boolean;
}

export interface IntegrationPreset {
  id: string;
  name: string;
  auth_methods: (AuthMethod | null)[];
  required_org_credential_fields: CredentialField[];
  setup_instructions: string | null;
}

export interface IntegrationCreate {
  for_organization: boolean;
  name: string;
  description: string | null;
  auth_mode: AuthMode;
  auth_method: AuthMethod | null;
  credential_fields?: CredentialField[] | null;
  header_template: Record<string, string> | null;
  oauth_client: OAuthClientInput | null;
  config: IntegrationConfig;
}

export interface IntegrationUpdate {
  name?: string;
  description?: string | null;
  enabled?: boolean;
  auth_mode?: AuthMode;
  auth_method?: AuthMethod | null;
  credential_fields?: CredentialField[] | null;
  header_template?: Record<string, string> | null;
  users_can_save_always_allow?: boolean;
  oauth_client?: OAuthClientInput | null;
  config?: IntegrationConfig;
}

export interface IntegrationActionsResponse {
  default_policy: PolicyValue | null;
  actions: IntegrationAction[];
}

export interface IntegrationActionsUpdate {
  default_policy: PolicyValue | null;
  actions: Record<string, PolicyValue | null>;
}

export interface AdminPluginEntry {
  plugin: IntegrationPluginRef;
  integrations: AdminIntegration[];
}
