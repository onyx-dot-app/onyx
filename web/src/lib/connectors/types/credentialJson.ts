/** The `credential_json` shape of each source. */
import type { TypedFile } from "../fileTypes";

export interface GithubCredentialJson {
  github_access_token: string;
  github_base_url: string | null;
}

export interface GitbookCredentialJson {
  gitbook_api_key: string;
}

export interface GitlabCredentialJson {
  gitlab_url: string;
  gitlab_access_token: string;
}

export interface LumAppsCredentialJson {
  lumapps_application_id: string;
  lumapps_api_key: string;
  lumapps_service_user: string;
}

export interface BitbucketCredentialJson {
  bitbucket_email: string;
  bitbucket_api_token: string;
}

export interface BookstackCredentialJson {
  bookstack_base_url: string;
  bookstack_api_token_id: string;
  bookstack_api_token_secret: string;
}

export interface OutlineCredentialJson {
  outline_base_url: string;
  outline_api_token: string;
}

export interface ConfluenceCredentialJson {
  confluence_username: string;
  confluence_access_token: string;
}

export interface JiraCredentialJson {
  jira_user_email: string | null;
  jira_api_token: string;
}

export interface JiraServerCredentialJson {
  jira_api_token: string;
}

export interface ProductboardCredentialJson {
  productboard_access_token: string;
}

export interface SlackCredentialJson {
  slack_bot_token: string;
}

export interface GmailCredentialJson {
  google_tokens: string;
  google_primary_admin: string;
}

export interface GoogleDriveCredentialJson {
  google_tokens: string;
  google_primary_admin: string;
  authentication_method?: string;
}

export interface GmailServiceAccountCredentialJson {
  google_service_account_key: string;
  google_primary_admin: string;
}

export interface GoogleDriveServiceAccountCredentialJson {
  google_service_account_key: string;
  google_primary_admin: string;
  authentication_method?: string;
}

export interface SlabCredentialJson {
  slab_bot_token: string;
}

export interface CodaCredentialJson {
  coda_bearer_token: string;
}

export interface NotionCredentialJson {
  notion_integration_token: string;
}

export interface ZulipCredentialJson {
  zuliprc_content: string;
}

export interface GuruCredentialJson {
  guru_user: string;
  guru_user_token: string;
}

export interface GongCredentialJson {
  gong_access_key: string;
  gong_access_key_secret: string;
  gong_base_url: string | null;
}

export interface LoopioCredentialJson {
  loopio_subdomain: string;
  loopio_client_id: string;
  loopio_client_token: string;
}

export interface LinearCredentialJson {
  linear_api_key: string;
}

export interface HubSpotCredentialJson {
  hubspot_access_token: string;
}

export interface Document360CredentialJson {
  portal_id: string;
  document360_api_token: string;
}

export interface ClickupCredentialJson {
  clickup_api_token: string;
  clickup_team_id: string;
}

export interface ZendeskCredentialJson {
  zendesk_subdomain: string;
  zendesk_email: string;
  zendesk_token: string;
}

export interface BoxCredentialJson {
  box_client_id: string;
  box_client_secret: string;
  box_enterprise_id: string;
  box_user_email: string | null;
}

export interface DropboxCredentialJson {
  dropbox_access_token: string;
}

export interface R2CredentialJson {
  account_id: string;
  r2_access_key_id: string;
  r2_secret_access_key: string;
}

export interface S3CredentialJson {
  aws_access_key_id?: string;
  aws_secret_access_key?: string;
  aws_role_arn?: string;
}

export interface GCSCredentialJson {
  access_key_id: string;
  secret_access_key: string;
}

export interface OCICredentialJson {
  namespace: string;
  region: string;
  access_key_id: string;
  secret_access_key: string;
}
export interface SalesforceLegacyCredentialJson {
  authentication_method?: "password";
  sf_username: string;
  sf_password: string;
  sf_security_token: string;
  is_sandbox: boolean;
}

export interface SalesforceOAuthCredentialJson {
  authentication_method: "oauth";
  sf_access_token: string;
  sf_refresh_token: string;
  sf_instance_url: string;
  sf_login_url: string;
}

export type SalesforceCredentialJson =
  | SalesforceLegacyCredentialJson
  | SalesforceOAuthCredentialJson;

export interface SharepointCredentialJson {
  sp_client_id: string;
  sp_client_secret?: string;
  sp_directory_id: string;
  sp_certificate_password?: string;
  sp_private_key?: TypedFile;
}

export type OneDriveAuthenticationMethod = "client_secret" | "certificate";

export interface OneDriveCredentialJson {
  authentication_method: OneDriveAuthenticationMethod;
  onedrive_client_id: string;
  onedrive_directory_id: string;
  onedrive_client_secret?: string;
  onedrive_certificate_password?: string;
  onedrive_private_key?: TypedFile | null;
}

export interface AsanaCredentialJson {
  asana_api_token_secret: string;
}

export interface TeamsCredentialJson {
  teams_client_id: string;
  teams_client_secret?: string;
  teams_directory_id: string;
  teams_certificate_password?: string;
  teams_private_key?: TypedFile;
}

export interface OutlookCredentialJson {
  outlook_client_id: string;
  outlook_client_secret?: string;
  outlook_directory_id: string;
  outlook_certificate_password?: string;
  outlook_private_key?: TypedFile;
}

export interface DiscourseCredentialJson {
  discourse_api_key: string;
  discourse_api_username: string;
}

export interface AxeroCredentialJson {
  base_url: string;
  axero_api_token: string;
}

export interface DiscordCredentialJson {
  discord_bot_token: string;
}

export interface FreshdeskCredentialJson {
  freshdesk_domain: string;
  freshdesk_api_key: string;
}

export interface FirefliesCredentialJson {
  fireflies_api_key: string;
}

export interface BraintrustCredentialJson {
  braintrust_api_key: string;
}

export interface CanvasCredentialJson {
  canvas_access_token: string;
}

export interface MediaWikiCredentialJson {}
export interface WikipediaCredentialJson extends MediaWikiCredentialJson {}

export interface EgnyteCredentialJson {
  domain: string;
  access_token: string;
}

export interface AirtableCredentialJson {
  airtable_access_token: string;
}

export interface HighspotCredentialJson {
  highspot_url: string;
  highspot_key: string;
  highspot_secret: string;
}

export interface DrupalWikiCredentialJson {
  drupal_wiki_api_token: string;
}

export interface ImapCredentialJson {
  imap_username: string;
  imap_password: string;
}

export interface TestRailCredentialJson {
  testrail_base_url: string;
  testrail_username: string;
  testrail_api_key: string;
}
