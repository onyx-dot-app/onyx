/** The `connector_specific_config` shape of each source. */

export interface UrlRewriteRule {
  source: string;
  target: string;
}

export interface WebConfig {
  base_url: string;
  web_connector_type?: "recursive" | "single" | "sitemap";
  url_rewrites?: UrlRewriteRule[];
}

export interface GithubConfig {
  repo_owner: string;
  repositories: string; // Comma-separated list of repository names
  include_prs: boolean;
  include_issues: boolean;
  include_files: boolean;
  branch?: string;
}

export interface GitlabConfig {
  project_owner: string;
  project_name: string;
  include_mrs: boolean;
  include_issues: boolean;
}

export interface LumAppsConfig {
  base_url: string;
  organization_id: string;
  instance_ids?: string[];
  custom_content_types?: string[];
  lang?: string;
}

export interface BitbucketConfig {
  workspace: string;
  repositories?: string;
  projects?: string;
}

export interface GoogleDriveConfig {
  include_shared_drives?: boolean;
  shared_drive_urls?: string;
  include_my_drives?: boolean;
  my_drive_emails?: string;
  shared_folder_urls?: string;
}

export interface GmailConfig {}

export interface BookstackConfig {}

export interface OutlineConfig {}

export interface ConfluenceConfig {
  wiki_base: string;
  space?: string;
  page_id?: string;
  is_cloud?: boolean;
  index_recursively?: boolean;
  cql_query?: string;
  include_attachments?: boolean;
}

export interface JiraConfig {
  jira_project_url: string;
  project_key?: string;
  comment_email_blacklist?: string[];
  jql_query?: string;
}

export interface JiraServiceManagementConfig {
  jira_base_url: string;
  project_key: string;
  scoped_token?: boolean;
  comment_email_blacklist?: string[];
  jql_query?: string;
  include_internal_comments?: boolean;
  include_attachments?: boolean;
}

export interface SalesforceConfig {
  requested_objects?: string[];
}

export interface SharepointConfig {
  sites?: string[];
  include_site_pages?: boolean;
  treat_sharing_link_as_public?: boolean;
  include_site_documents?: boolean;
  authority_host?: string;
  graph_api_host?: string;
  sharepoint_domain_suffix?: string;
}

export interface TeamsConfig {
  teams?: string[];
  include_attachments?: boolean;
  include_inline_images?: boolean;
  include_meeting_transcripts?: boolean;
  include_meeting_chats?: boolean;
  meeting_organizers?: string[];
  authority_host?: string;
  graph_api_host?: string;
}

export interface DiscourseConfig {
  base_url: string;
  categories?: string[];
}

export interface AxeroConfig {
  spaces?: string[];
}

export interface CanvasConfig {
  canvas_base_url: string;
}

export interface DrupalWikiConfig {
  base_url: string;
  spaces?: string[];
  pages?: string[];
  include_attachments?: boolean;
}

export interface ProductboardConfig {}

export interface SlackConfig {
  workspace: string;
  channels?: string[];
  channel_regex_enabled?: boolean;
  exclude_channels?: string[];
  exclude_channel_regex_enabled?: boolean;
  include_bot_messages?: boolean;
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
  file_names: string[];
  zip_metadata_file_id: string | null;
}

export interface ZulipConfig {
  realm_name: string;
  realm_url: string;
}

export interface CodaConfig {
  workspace_id?: string;
}

export interface NotionConfig {
  root_page_id?: string;
}

export interface HubSpotConfig {
  object_types?: string[];
}

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

export interface XenforoConfig {
  base_url: string;
}

export interface ZendeskConfig {
  content_type?: "articles" | "tickets";
  calls_per_minute?: number;
}

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
  european_residency?: boolean;
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

export interface AsanaConfig {
  asana_workspace_id: string;
  asana_project_ids?: string;
  asana_team_id?: string;
}

export interface FreshdeskConfig {}

export interface FirefliesConfig {}

export interface MediaWikiConfig extends MediaWikiBaseConfig {
  hostname: string;
}

export interface WikipediaConfig extends MediaWikiBaseConfig {}

export interface ImapConfig {
  host: string;
  port?: number;
  mailboxes?: string[];
}
