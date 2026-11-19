export type IntegrationKind = "mcp" | "api";
export type IntegrationShape = "mcp_server" | "openapi" | "preset" | "custom";
export type AuthMode = "none" | "shared" | "individual";
export type AuthMethod = "oauth2" | "api_key" | "onyx_login" | "managed";
export type ConnectionState =
  | "connected"
  | "not_connected"
  | "needs_reconnect"
  | "not_set_up";
export type PolicyValue = "allow" | "ask" | "blocked";

export type LinkValue = "inherit" | PolicyValue;
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

/** What one user gets from an integration (`access.state`). */
export type MemberIntegrationState =
  | "on"
  | "turn_on"
  | "sign_in"
  | "no_access"
  | "turned_off";

/** The access facts of one integration for the user who reads it. */
export interface IntegrationAccess {
  state: MemberIntegrationState;
  /** The install setting for the user, with the group settings. */
  installation_policy: InstallationPolicy;
  /** The saved on/off choice of the user. Null: the user made no choice. */
  user_choice: boolean | null;
  /** The choice under the install setting. */
  user_enabled: boolean;
  owner_email: string | null;
  is_owner: boolean;
  /** The user can change the integration, its shares and its actions. */
  can_manage: boolean;
  /** The company setting is above Not available, so each user has access. */
  shared_with_everyone: boolean;
}

/** The shares of a private integration. A share gives use only. */
export interface IntegrationSharesView {
  integration_id: number;
  user_shares: { user_id: string; email: string }[];
  group_shares: { group_id: number; group_name: string }[];
}

/** The new set of shares; a share left out is removed. */
export interface IntegrationSharesUpdate {
  user_ids: string[];
  group_ids: number[];
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

/** One integration in `GET /integrations/agent-catalog`. */
export interface AgentCatalogIntegration {
  id: number;
  name: string;
  description: string | null;
  kind: IntegrationKind;
  shape: IntegrationShape;
  users_can_save_always_allow: boolean;
  actions: IntegrationAction[];
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
  /** The company install setting. */
  installation_policy: InstallationPolicy;
  /** What the user who reads the row gets from the integration. */
  access: IntegrationAccess;
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
  /** The groups with their own install setting. */
  group_settings: IntegrationGroupSetting[];
  /** The groups with a share. A shared group cannot be Not available. */
  group_shares: { group_id: number; group_name: string }[];
}

export interface IntegrationGroupSetting {
  group_id: number;
  group_name: string;
  installation_policy: InstallationPolicy;
}

/** One group to change. Null removes the setting of the group. */
export interface IntegrationGroupSettingChange {
  group_id: number;
  installation_policy: InstallationPolicy | null;
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
  /** Left out, the default row stays as it is. */
  default_policy?: PolicyValue | null;
  actions: Record<string, PolicyValue | null>;
}

export interface MemberIntegration {
  id: number;
  kind: IntegrationKind;
  shape: IntegrationShape;
  name: string;
  description: string | null;
  preset_id: string | null;
  auth_mode: AuthMode;
  auth_method: AuthMethod | null;
  credential_fields: CredentialField[];
  status: IntegrationStatus;
  access: IntegrationAccess;
  users_can_save_always_allow: boolean;
  /** The user's saved credential values, masked. */
  credential_values: Record<string, string>;
  external_app_id: number | null;
  service_urls: string[];
  mcp_server_id: number | null;
  server_url: string | null;
}

export interface MemberAction extends IntegrationAction {
  /** The user's saved "Always allow". */
  user_policy: "allow" | null;
}

export interface MemberActionPolicies {
  users_can_save_always_allow: boolean;
  actions: MemberAction[];
}

export interface IntegrationOAuthCallbackResult {
  integration_id: number;
  return_path: string | null;
}
