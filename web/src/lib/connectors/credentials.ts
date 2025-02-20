import { ValidSources } from "../types";

export interface OAuthAdditionalKwargDescription {
  name: string;
  display_name: string;
  description: string;
}

export interface OAuthDetails {
  oauth_enabled: boolean;
  additional_kwargs: OAuthAdditionalKwargDescription[];
}

export interface CredentialBase<T> {
  credential_json: T;
  admin_public: boolean;
  source: ValidSources;
  name?: string;
  curator_public?: boolean;
  groups?: number[];
}

export interface Credential<T> extends CredentialBase<T> {
  id: number;
  user_id: string | null;
  time_created: string;
  time_updated: string;
}
export interface GithubCredentialJson {
  github_access_token: string;
}

export interface GitbookCredentialJson {
  gitbook_api_key: string;
}

export interface GitlabCredentialJson {
  gitlab_url: string;
  gitlab_access_token: string;
}

export interface BookstackCredentialJson {
  bookstack_base_url: string;
  bookstack_api_token_id: string;
  bookstack_api_token_secret: string;
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
}

export interface LoopioCredentialJson {
  loopio_subdomain: string;
  loopio_client_id: string;
  loopio_client_token: string;
}

export interface LinearCredentialJson {
  linear_access_token: string;
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

export interface DropboxCredentialJson {
  dropbox_access_token: string;
}

export interface R2CredentialJson {
  account_id: string;
  r2_access_key_id: string;
  r2_secret_access_key: string;
}

export interface S3CredentialJson {
  aws_access_key_id: string;
  aws_secret_access_key: string;
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
export interface SalesforceCredentialJson {
  sf_username: string;
  sf_password: string;
  sf_security_token: string;
}

export interface SharepointCredentialJson {
  sp_client_id: string;
  sp_client_secret: string;
  sp_directory_id: string;
}

export interface AsanaCredentialJson {
  asana_api_token_secret: string;
}

export interface TeamsCredentialJson {
  teams_client_id: string;
  teams_client_secret: string;
  teams_directory_id: string;
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
  freshdesk_password: string;
  freshdesk_api_key: string;
}

export interface FirefliesCredentialJson {
  fireflies_api_key: string;
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

export const credentialTemplates: Record<ValidSources, any> = {
  github: { github_access_token: "" } as GithubCredentialJson,
  gitlab: {
    gitlab_url: "",
    gitlab_access_token: "",
  } as GitlabCredentialJson,
  slack: { slack_bot_token: "" } as SlackCredentialJson,
  bookstack: {
    bookstack_base_url: "",
    bookstack_api_token_id: "",
    bookstack_api_token_secret: "",
  } as BookstackCredentialJson,
  confluence: {
    confluence_username: "",
    confluence_access_token: "",
  } as ConfluenceCredentialJson,
  jira: {
    jira_user_email: null,
    jira_api_token: "",
  } as JiraCredentialJson,
  productboard: { productboard_access_token: "" } as ProductboardCredentialJson,
  slab: { slab_bot_token: "" } as SlabCredentialJson,
  notion: { notion_integration_token: "" } as NotionCredentialJson,
  guru: { guru_user: "", guru_user_token: "" } as GuruCredentialJson,
  gong: {
    gong_access_key: "",
    gong_access_key_secret: "",
  } as GongCredentialJson,
  zulip: { zuliprc_content: "" } as ZulipCredentialJson,
  linear: { linear_access_token: "" } as LinearCredentialJson,
  hubspot: { hubspot_access_token: "" } as HubSpotCredentialJson,
  document360: {
    portal_id: "",
    document360_api_token: "",
  } as Document360CredentialJson,
  loopio: {
    loopio_subdomain: "",
    loopio_client_id: "",
    loopio_client_token: "",
  } as LoopioCredentialJson,
  dropbox: { dropbox_access_token: "" } as DropboxCredentialJson,
  salesforce: {
    sf_username: "",
    sf_password: "",
    sf_security_token: "",
  } as SalesforceCredentialJson,
  sharepoint: {
    sp_client_id: "",
    sp_client_secret: "",
    sp_directory_id: "",
  } as SharepointCredentialJson,
  asana: {
    asana_api_token_secret: "",
  } as AsanaCredentialJson,
  teams: {
    teams_client_id: "",
    teams_client_secret: "",
    teams_directory_id: "",
  } as TeamsCredentialJson,
  zendesk: {
    zendesk_subdomain: "",
    zendesk_email: "",
    zendesk_token: "",
  } as ZendeskCredentialJson,
  discourse: {
    discourse_api_key: "",
    discourse_api_username: "",
  } as DiscourseCredentialJson,
  axero: {
    base_url: "",
    axero_api_token: "",
  } as AxeroCredentialJson,
  clickup: {
    clickup_api_token: "",
    clickup_team_id: "",
  } as ClickupCredentialJson,
  s3: {
    aws_access_key_id: "",
    aws_secret_access_key: "",
  } as S3CredentialJson,
  r2: {
    account_id: "",
    r2_access_key_id: "",
    r2_secret_access_key: "",
  } as R2CredentialJson,
  google_cloud_storage: {
    access_key_id: "",
    secret_access_key: "",
  } as GCSCredentialJson,
  oci_storage: {
    namespace: "",
    region: "",
    access_key_id: "",
    secret_access_key: "",
  } as OCICredentialJson,
  freshdesk: {
    freshdesk_domain: "",
    freshdesk_password: "",
    freshdesk_api_key: "",
  } as FreshdeskCredentialJson,
  fireflies: {
    fireflies_api_key: "",
  } as FirefliesCredentialJson,
  egnyte: {
    domain: "",
    access_token: "",
  } as EgnyteCredentialJson,
  airtable: {
    airtable_access_token: "",
  } as AirtableCredentialJson,
  xenforo: null,
  google_sites: null,
  file: null,
  wikipedia: null,
  mediawiki: null,
  web: null,
  not_applicable: null,
  ingestion_api: null,
  discord: { discord_bot_token: "" } as DiscordCredentialJson,

  // NOTE: These are Special Cases
  google_drive: { google_tokens: "" } as GoogleDriveCredentialJson,
  gmail: { google_tokens: "" } as GmailCredentialJson,
  gitbook: {
    gitbook_api_key: "",
  } as GitbookCredentialJson,
};

export const credentialDisplayNames: Record<string, string> = {
  // Github
  github_access_token: "GitHub Access Token",

  // Gitlab
  gitlab_url: "GitLab URL",
  gitlab_access_token: "GitLab Access Token",

  // Bookstack
  bookstack_base_url: "Bookstack Base URL",
  bookstack_api_token_id: "Bookstack API Token ID",
  bookstack_api_token_secret: "Bookstack API Token Secret",

  // Confluence
  confluence_username: "Confluence Username",
  confluence_access_token: "Confluence Access Token",

  // Jira
  jira_user_email: "Jira User Email (required for Jira Cloud)",
  jira_api_token: "API or Personal Access Token",

  // Productboard
  productboard_access_token: "Productboard Access Token",

  // Slack
  slack_bot_token: "Slack Bot Token",

  // Discord
  discord_bot_token: "Discord Bot Token",

  // Gmail and Google Drive
  google_tokens: "Google Oauth Tokens",
  google_service_account_key: "Google Service Account Key",
  google_primary_admin: "Primary Admin Email",

  // Slab
  slab_bot_token: "Slab Bot Token",

  // Notion
  notion_integration_token: "Notion Integration Token",

  // Zulip
  zuliprc_content: "Zuliprc Content",

  // Guru
  guru_user: "Guru User",
  guru_user_token: "Guru User Token",

  // Gong
  gong_access_key: "Gong Access Key",
  gong_access_key_secret: "Gong Access Key Secret",

  // Loopio
  loopio_subdomain: "Loopio Subdomain",
  loopio_client_id: "Loopio Client ID",
  loopio_client_token: "Loopio Client Token",

  // Linear
  linear_access_token: "Linear Access Token",

  // HubSpot
  hubspot_access_token: "HubSpot Access Token",
  // Document360
  portal_id: "Document360 Portal ID",
  document360_api_token: "Document360 API Token",

  // Clickup
  clickup_api_token: "ClickUp API Token",
  clickup_team_id: "ClickUp Team ID",

  // Zendesk
  zendesk_subdomain: "Zendesk Subdomain",
  zendesk_email: "Zendesk Email",
  zendesk_token: "Zendesk Token",

  // Dropbox
  dropbox_access_token: "Dropbox API Key",

  // R2
  account_id: "R2 Account ID",
  r2_access_key_id: "R2 Access Key ID",
  r2_secret_access_key: "R2 Secret Access Key",

  // S3
  aws_access_key_id: "AWS Access Key ID",
  aws_secret_access_key: "AWS Secret Access Key",

  // GCS
  access_key_id: "GCS Access Key ID",
  secret_access_key: "GCS Secret Access Key",

  // OCI
  namespace: "OCI Namespace",
  region: "OCI Region",

  // Salesforce
  sf_username: "Salesforce Username",
  sf_password: "Salesforce Password",
  sf_security_token: "Salesforce Security Token",

  // Sharepoint
  sp_client_id: "SharePoint Client ID",
  sp_client_secret: "SharePoint Client Secret",
  sp_directory_id: "SharePoint Directory ID",

  // Asana
  asana_api_token_secret: "Asana API Token",

  // Teams
  teams_client_id: "Microsoft Teams Client ID",
  teams_client_secret: "Microsoft Teams Client Secret",
  teams_directory_id: "Microsoft Teams Directory ID",

  // Discourse
  discourse_api_key: "Discourse API Key",
  discourse_api_username: "Discourse API Username",

  // Axero
  base_url: "Axero Base URL",
  axero_api_token: "Axero API Token",

  // Freshdesk
  freshdesk_domain: "Freshdesk Domain",
  freshdesk_password: "Freshdesk Password",
  freshdesk_api_key: "Freshdesk API Key",

  // Fireflies
  fireflies_api_key: "Fireflies API Key",

  // GitBook
  gitbook_space_id: "GitBook Space ID",
  gitbook_api_key: "GitBook API Key",
};

export function getDisplayNameForCredentialKey(key: string): string {
  return credentialDisplayNames[key] || key;
}
