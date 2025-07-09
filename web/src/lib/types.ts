import { Persona } from "@/app/admin/assistants/interfaces";
import { Credential } from "./connectors/credentials";
import { Connector } from "./connectors/connectors";
import { ConnectorCredentialPairStatus } from "@/app/admin/connector/[ccPairId]/types";

interface UserPreferences {
  chosen_assistants: number[] | null;
  visible_assistants: number[];
  hidden_assistants: number[];
  pinned_assistants?: number[];
  default_model: string | null;
  recent_assistants: number[];
  auto_scroll: boolean;
  shortcut_enabled: boolean;
  temperature_override_enabled: boolean;
}

export enum UserRole {
  LIMITED = "limited",
  BASIC = "basic",
  ADMIN = "admin",
  CURATOR = "curator",
  GLOBAL_CURATOR = "global_curator",
  EXT_PERM_USER = "ext_perm_user",
  SLACK_USER = "slack_user",
}

export const USER_ROLE_LABELS: Record<UserRole, string> = {
  [UserRole.BASIC]: "Basic",
  [UserRole.ADMIN]: "Admin",
  [UserRole.GLOBAL_CURATOR]: "Global Curator",
  [UserRole.CURATOR]: "Curator",
  [UserRole.LIMITED]: "Limited",
  [UserRole.EXT_PERM_USER]: "External Permissioned User",
  [UserRole.SLACK_USER]: "Slack User",
};

export const INVALID_ROLE_HOVER_TEXT: Partial<Record<UserRole, string>> = {
  [UserRole.BASIC]: "Basic users can't perform any admin actions",
  [UserRole.ADMIN]: "Admin users can perform all admin actions",
  [UserRole.GLOBAL_CURATOR]:
    "Global Curator users can perform admin actions for all groups they are a member of",
  [UserRole.CURATOR]: "Curator role must be assigned in the Groups tab",
  [UserRole.SLACK_USER]:
    "This role is automatically assigned to users who only use Onyx via Slack",
};

export interface User {
  id: string;
  email: string;
  is_active: boolean;
  is_superuser: boolean;
  is_verified: boolean;
  role: UserRole;
  preferences: UserPreferences;
  current_token_created_at?: Date;
  current_token_expiry_length?: number;
  oidc_expiry?: Date;
  is_cloud_superuser?: boolean;
  team_name: string | null;
  is_anonymous_user?: boolean;
  // If user does not have a configured password
  // (i.e.) they are using an oauth flow
  // or are in a no-auth situation
  // we don't want to show them things like the reset password
  // functionality
  password_configured?: boolean;
  tenant_info?: TenantInfo | null;
}

export interface TenantInfo {
  new_tenant?: NewTenantInfo | null;
  invitation?: NewTenantInfo | null;
}

export interface NewTenantInfo {
  tenant_id: string;
  number_of_users: number;
}

export interface AllUsersResponse {
  accepted: User[];
  invited: User[];
  slack_users: User[];
  accepted_pages: number;
  invited_pages: number;
  slack_users_pages: number;
}

export interface AcceptedUserSnapshot {
  id: string;
  email: string;
  role: UserRole;
  is_active: boolean;
}

export interface InvitedUserSnapshot {
  email: string;
}

export interface MinimalUserSnapshot {
  id: string;
  email: string;
}

export type ValidInputTypes =
  | "load_state"
  | "poll"
  | "event"
  | "slim_retrieval";
export type ValidStatuses =
  | "invalid"
  | "success"
  | "completed_with_errors"
  | "canceled"
  | "failed"
  | "in_progress"
  | "not_started";
export type TaskStatus = "PENDING" | "STARTED" | "SUCCESS" | "FAILURE";
export type Feedback = "like" | "dislike" | "mixed";
export type AccessType = "public" | "private" | "sync";
export type SessionType = "Chat" | "Search" | "Slack";

export interface DocumentBoostStatus {
  document_id: string;
  semantic_id: string;
  link: string;
  boost: number;
  hidden: boolean;
}

export interface FailedConnectorIndexingStatus {
  cc_pair_id: number;
  name: string | null;
  error_msg: string | null;
  is_deletable: boolean;
  connector_id: number;
  credential_id: number;
}

export interface IndexAttemptSnapshot {
  id: number;
  status: ValidStatuses | null;
  from_beginning: boolean;
  new_docs_indexed: number;
  docs_removed_from_index: number;
  total_docs_indexed: number;
  error_msg: string | null;
  error_count: number;
  full_exception_trace: string | null;
  time_started: string | null;
  time_updated: string;
}

export interface ConnectorStatus<ConnectorConfigType, ConnectorCredentialType> {
  cc_pair_id: number;
  name: string | null;
  connector: Connector<ConnectorConfigType>;
  credential: Credential<ConnectorCredentialType>;
  access_type: AccessType;
  groups: number[];
}

export interface ConnectorIndexingStatus<
  ConnectorConfigType,
  ConnectorCredentialType,
> extends ConnectorStatus<ConnectorConfigType, ConnectorCredentialType> {
  // Inlcude data only necessary for indexing statuses in admin page
  last_success: string | null;
  last_status: ValidStatuses | null;
  last_finished_status: ValidStatuses | null;
  cc_pair_status: ConnectorCredentialPairStatus;
  in_repeated_error_state: boolean;
  latest_index_attempt: IndexAttemptSnapshot | null;
  docs_indexed: number;
}

export interface FederatedConnectorDetail {
  id: number;
  source: ValidSources.FederatedSlack;
  name: string;
  credentials: Record<string, any>;
  oauth_token_exists: boolean;
  oauth_token_expires_at: string | null;
  document_sets: Array<{
    id: number;
    name: string;
    entities: Record<string, any>;
  }>;
}

export interface OAuthPrepareAuthorizationResponse {
  url: string;
}

export interface OAuthBaseCallbackResponse {
  success: boolean;
  message: string;
  finalize_url: string | null;
  redirect_on_success: string;
}

export interface OAuthSlackCallbackResponse extends OAuthBaseCallbackResponse {
  team_id: string;
  authed_user_id: string;
}

export interface ConfluenceAccessibleResource {
  id: string;
  name: string;
  url: string;
  scopes: string[];
  avatarUrl: string;
}

export interface OAuthConfluencePrepareFinalizationResponse {
  success: boolean;
  message: string;
  accessible_resources: ConfluenceAccessibleResource[];
}

export interface OAuthConfluenceFinalizeResponse {
  success: boolean;
  message: string;
  redirect_url: string;
}

export interface CCPairBasicInfo {
  has_successful_run: boolean;
  source: ValidSources;
}

export type ConnectorSummary = {
  count: number;
  active: number;
  public: number;
  totalDocsIndexed: number;
  errors: number; // New field for error count
};

export type GroupedConnectorSummaries = Record<ValidSources, ConnectorSummary>;

// DELETION

export interface DeletionAttemptSnapshot {
  connector_id: number;
  credential_id: number;
  status: TaskStatus;
}

// DOCUMENT SETS
export interface CCPairDescriptor<ConnectorType, CredentialType> {
  id: number;
  name: string | null;
  connector: Connector<ConnectorType>;
  credential: Credential<CredentialType>;
  access_type: AccessType;
}

export interface FederatedConnectorConfig {
  federated_connector_id: number;
  entities: Record<string, any>;
}

export interface FederatedConnectorDescriptor {
  id: number;
  name: string;
  source: string;
  entities: Record<string, any>;
}

export interface DocumentSet {
  id: number;
  name: string;
  description: string;
  cc_pair_descriptors: CCPairDescriptor<any, any>[];
  is_up_to_date: boolean;
  is_public: boolean;
  users: string[];
  groups: number[];
  federated_connectors: FederatedConnectorDescriptor[];
}

export interface Tag {
  tag_key: string;
  tag_value: string;
  source: ValidSources;
}

// STANDARD ANSWERS
export interface StandardAnswerCategory {
  id: number;
  name: string;
}

export interface StandardAnswer {
  id: number;
  keyword: string;
  answer: string;
  match_regex: boolean;
  match_any_keywords: boolean;
  categories: StandardAnswerCategory[];
}

// SLACK BOT CONFIGS

export type AnswerFilterOption =
  | "well_answered_postfilter"
  | "questionmark_prefilter";

export interface ChannelConfig {
  channel_name: string;
  respond_tag_only?: boolean;
  respond_to_bots?: boolean;
  is_ephemeral?: boolean;
  show_continue_in_web_ui?: boolean;
  respond_member_group_list?: string[];
  answer_filters?: AnswerFilterOption[];
  follow_up_tags?: string[];
  disabled?: boolean;
}

export type SlackBotResponseType = "quotes" | "citations";

export interface SlackChannelConfig {
  id: number;
  slack_bot_id: number;
  persona_id: number | null;
  persona: Persona | null;
  channel_config: ChannelConfig;
  enable_auto_filters: boolean;
  standard_answer_categories: StandardAnswerCategory[];
  is_default: boolean;
}

export interface SlackChannelDescriptor {
  id: string;
  name: string;
}

export type SlackBot = {
  id: number;
  name: string;
  enabled: boolean;
  configs_count: number;
  slack_channel_configs: Array<{
    id: number;
    is_default: boolean;
    channel_config: {
      channel_name: string;
    };
  }>;
  bot_token: string;
  app_token: string;
};

export interface SlackBotTokens {
  bot_token: string;
  app_token: string;
}

/* EE Only Types */
export interface UserGroup {
  id: number;
  name: string;
  users: User[];
  curator_ids: string[];
  cc_pairs: CCPairDescriptor<any, any>[];
  document_sets: DocumentSet[];
  personas: Persona[];
  is_up_to_date: boolean;
  is_up_for_deletion: boolean;
}

export enum ValidSources {
  Web = "web",
  GitHub = "github",
  GitLab = "gitlab",
  Slack = "slack",
  GoogleDrive = "google_drive",
  Gmail = "gmail",
  Bookstack = "bookstack",
  Confluence = "confluence",
  Jira = "jira",
  Productboard = "productboard",
  Slab = "slab",
  Notion = "notion",
  Guru = "guru",
  Gong = "gong",
  Zulip = "zulip",
  Linear = "linear",
  Hubspot = "hubspot",
  Document360 = "document360",
  File = "file",
  GoogleSites = "google_sites",
  Loopio = "loopio",
  Dropbox = "dropbox",
  Discord = "discord",
  Salesforce = "salesforce",
  Sharepoint = "sharepoint",
  Teams = "teams",
  Zendesk = "zendesk",
  Discourse = "discourse",
  Axero = "axero",
  Clickup = "clickup",
  Wikipedia = "wikipedia",
  Mediawiki = "mediawiki",
  Asana = "asana",
  S3 = "s3",
  R2 = "r2",
  GoogleCloudStorage = "google_cloud_storage",
  Xenforo = "xenforo",
  OciStorage = "oci_storage",
  NotApplicable = "not_applicable",
  IngestionApi = "ingestion_api",
  Freshdesk = "freshdesk",
  Fireflies = "fireflies",
  Egnyte = "egnyte",
  Airtable = "airtable",
  Gitbook = "gitbook",
  Highspot = "highspot",

  // Federated Connectors
  FederatedSlack = "federated_slack",
}

export const federatedSourceToRegularSource = (
  maybeFederatedSource: ValidSources
): ValidSources => {
  if (maybeFederatedSource === ValidSources.FederatedSlack) {
    return ValidSources.Slack;
  }
  return maybeFederatedSource;
};

export const validAutoSyncSources = [
  ValidSources.Confluence,
  ValidSources.GoogleDrive,
  ValidSources.Gmail,
  ValidSources.Slack,
  ValidSources.Salesforce,
] as const;

// Create a type from the array elements
export type ValidAutoSyncSource = (typeof validAutoSyncSources)[number];

export type ConfigurableSources = Exclude<
  ValidSources,
  | ValidSources.NotApplicable
  | ValidSources.IngestionApi
  | ValidSources.FederatedSlack // is part of ValiedSources.Slack
>;

export const oauthSupportedSources: ConfigurableSources[] = [
  ValidSources.Slack,
  // NOTE: temporarily disabled until our GDrive App is approved
  // ValidSources.GoogleDrive,
  ValidSources.Confluence,
];

export type OAuthSupportedSource = (typeof oauthSupportedSources)[number];

// Federated Connector Types
export interface CredentialFieldSpec {
  type: string;
  description: string;
  required: boolean;
  default?: any;
  example?: any;
  secret: boolean;
}

export interface CredentialSchemaResponse {
  credentials: Record<string, CredentialFieldSpec>;
}

export interface FederatedConnectorCreateRequest {
  source: string;
  credentials: Record<string, any>;
}

export interface FederatedConnectorCreateResponse {
  id: number;
  source: string;
}
