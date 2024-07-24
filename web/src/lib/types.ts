import { Persona } from "@/app/admin/assistants/interfaces";
import { Credential } from "./ccs/credentials";

export interface UserPreferences {
  chosen_assistants: number[] | null;
}

export enum UserStatus {
  live = "live",
  invited = "invited",
  deactivated = "deactivated",
}

export interface User {
  id: string;
  email: string;
  is_active: string;
  is_superuser: string;
  is_verified: string;
  role: "basic" | "admin";
  preferences: UserPreferences;
  status: UserStatus;
}

export interface MinimalUserSnapshot {
  id: string;
  email: string;
}

export type ValidInputTypes = "load_state" | "poll" | "event";
export type ValidStatuses =
  | "success"
  | "failed"
  | "in_progress"
  | "not_started";
export type TaskStatus = "PENDING" | "STARTED" | "SUCCESS" | "FAILURE";
export type Feedback = "like" | "dislike";

export interface DocumentBoostStatus {
  document_id: string;
  semantic_id: string;
  link: string;
  boost: number;
  hidden: boolean;
}

// CONNECTORS
export interface ConnectorBase<T> {
  name: string;
  source: ValidSources;
  input_type: ValidInputTypes;
  connector_specific_config: T;
  refresh_freq: number | null;
  prune_freq: number | null;
  indexing_start: Date | null;
  disabled: boolean;
}

export interface Connector<T> extends ConnectorBase<T> {
  id: number;
  credential_ids: number[];
  time_created: string;
  time_updated: string;
}

export interface WebConfig {
  base_url: string;
  web_connector_type?: "recursive" | "single" | "sitemap";
}

export interface GithubConfig {
  repo_owner: string;
  repo_name: string;
  include_prs: boolean;
  include_issues: boolean;
}

export interface GitlabConfig {
  project_owner: string;
  project_name: string;
  include_mrs: boolean;
  include_issues: boolean;
}

export interface GoogleDriveConfig {
  folder_paths?: string[];
  include_shared?: boolean;
  follow_shortcuts?: boolean;
  only_org_public?: boolean;
}

export interface GmailConfig {}

export interface BookstackConfig {}

export interface ConfluenceConfig {
  wiki_page_url: string;
  index_origin?: boolean;
}

export interface JiraConfig {
  jira_project_url: string;
  comment_email_blacklist?: string[];
}

export interface SalesforceConfig {
  requested_objects?: string[];
}

export interface SharepointConfig {
  sites?: string[];
}

export interface TeamsConfig {
  teams?: string[];
}

export interface DiscourseConfig {
  base_url: string;
  categories?: string[];
}

export interface AxeroConfig {
  spaces?: string[];
}

export interface TeamsConfig {
  teams?: string[];
}

export interface ProductboardConfig {}

export interface SlackConfig {
  workspace: string;
  channels?: string[];
  channel_regex_enabled?: boolean;
}

export interface SlabConfig {
  base_url: string;
}

export interface GuruConfig {}

export interface GongConfig {
  workspaces?: string[];
}

export interface LoopioConfig {
  loopio_stack_name?: string;
}

export interface FileConfig {
  file_locations: string[];
}

export interface ZulipConfig {
  realm_name: string;
  realm_url: string;
}

export interface NotionConfig {
  root_page_id?: string;
}

export interface HubSpotConfig {}

export interface RequestTrackerConfig {}

export interface Document360Config {
  workspace: string;
  categories?: string[];
}

export interface ClickupConfig {
  connector_type: "list" | "folder" | "space" | "workspace";
  connector_ids?: string[];
  retrieve_task_comments: boolean;
}

export interface GoogleSitesConfig {
  zip_path: string;
  base_url: string;
}

export interface ZendeskConfig {}

export interface DropboxConfig {}

export interface S3Config {
  bucket_type: "s3";
  bucket_name: string;
  prefix: string;
}

export interface R2Config {
  bucket_type: "r2";
  bucket_name: string;
  prefix: string;
}

export interface GCSConfig {
  bucket_type: "google_cloud_storage";
  bucket_name: string;
  prefix: string;
}

export interface OCIConfig {
  bucket_type: "oci_storage";
  bucket_name: string;
  prefix: string;
}

export interface MediaWikiBaseConfig {
  connector_name: string;
  language_code: string;
  categories?: string[];
  pages?: string[];
  recurse_depth?: number;
}

export interface MediaWikiConfig extends MediaWikiBaseConfig {
  hostname: string;
}

export interface WikipediaConfig extends MediaWikiBaseConfig {}

export interface IndexAttemptSnapshot {
  id: number;
  status: ValidStatuses | null;
  new_docs_indexed: number;
  docs_removed_from_index: number;
  total_docs_indexed: number;
  error_msg: string | null;
  full_exception_trace: string | null;
  time_started: string | null;
  time_updated: string;
}

export interface ConnectorIndexingStatus<
  ConnectorConfigType,
  ConnectorCredentialType,
> {
  cc_pair_id: number;
  name: string | null;
  connector: Connector<ConnectorConfigType>;
  credential: Credential<ConnectorCredentialType>;
  public_doc: boolean;
  owner: string;
  last_status: ValidStatuses | null;
  last_success: string | null;
  docs_indexed: number;
  error_msg: string;
  latest_index_attempt: IndexAttemptSnapshot | null;
  deletion_attempt: DeletionAttemptSnapshot | null;
  is_deletable: boolean;
}

export interface CCPairBasicInfo {
  docs_indexed: number;
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
  categories: StandardAnswerCategory[];
}

// SLACK BOT CONFIGS

export type AnswerFilterOption =
  | "well_answered_postfilter"
  | "questionmark_prefilter";

export interface ChannelConfig {
  channel_names: string[];
  respond_tag_only?: boolean;
  respond_to_bots?: boolean;
  respond_member_group_list?: string[];
  answer_filters?: AnswerFilterOption[];
  follow_up_tags?: string[];
}

export type SlackBotResponseType = "quotes" | "citations";

export interface SlackBotConfig {
  id: number;
  persona: Persona | null;
  channel_config: ChannelConfig;
  response_type: SlackBotResponseType;
  standard_answer_categories: StandardAnswerCategory[];
  enable_auto_filters: boolean;
}

export interface SlackBotTokens {
  bot_token: string;
  app_token: string;
}

/* EE Only Types */
export interface UserGroup {
  id: number;
  name: string;
  users: User[];
  cc_pairs: CCPairDescriptor<any, any>[];
  document_sets: DocumentSet[];
  personas: Persona[];
  is_up_to_date: boolean;
  is_up_for_deletion: boolean;
}

const validSources = [
  "web",
  "github",
  "gitlab",
  "slack",
  "google_drive",
  "gmail",
  "bookstack",
  "confluence",
  "jira",
  "productboard",
  "slab",
  "notion",
  "guru",
  "gong",
  "zulip",
  "linear",
  "hubspot",
  "document360",
  "requesttracker",
  "file",
  "google_sites",
  "loopio",
  "dropbox",
  "salesforce",
  "sharepoint",
  "teams",
  "zendesk",
  "discourse",
  "axero",
  "clickup",
  "wikipedia",
  "mediawiki",
  "s3",
  "r2",
  "google_cloud_storage",
  "oci_storage",
  "not_applicable",
];

export type ValidSources = (typeof validSources)[number];
