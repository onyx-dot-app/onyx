import { ValidSources } from "../types";
import type {
  AirtableCredentialJson,
  AsanaCredentialJson,
  AxeroCredentialJson,
  BitbucketCredentialJson,
  BookstackCredentialJson,
  BoxCredentialJson,
  BraintrustCredentialJson,
  CanvasCredentialJson,
  ClickupCredentialJson,
  CodaCredentialJson,
  ConfluenceCredentialJson,
  CredentialTemplateWithAuth,
  DiscordCredentialJson,
  DiscourseCredentialJson,
  Document360CredentialJson,
  DropboxCredentialJson,
  DrupalWikiCredentialJson,
  EgnyteCredentialJson,
  FirefliesCredentialJson,
  FreshdeskCredentialJson,
  GCSCredentialJson,
  GitbookCredentialJson,
  GithubCredentialJson,
  GitlabCredentialJson,
  GmailCredentialJson,
  GongCredentialJson,
  GoogleDriveCredentialJson,
  GuruCredentialJson,
  HighspotCredentialJson,
  HubSpotCredentialJson,
  ImapCredentialJson,
  JiraCredentialJson,
  LinearCredentialJson,
  LoopioCredentialJson,
  LumAppsCredentialJson,
  NotionCredentialJson,
  OCICredentialJson,
  OutlineCredentialJson,
  OutlookCredentialJson,
  ProductboardCredentialJson,
  R2CredentialJson,
  S3CredentialJson,
  SalesforceCredentialJson,
  SharepointCredentialJson,
  SlabCredentialJson,
  SlackCredentialJson,
  TeamsCredentialJson,
  TestRailCredentialJson,
  ZendeskCredentialJson,
  ZulipCredentialJson,
} from "./types";

// Gmail and Google Drive use dedicated credential UIs, so their templates are partial.
type CredentialTemplateMap = Record<ValidSources, object | null> & {
  github: GithubCredentialJson;
  gitlab: GitlabCredentialJson;
  lumapps: LumAppsCredentialJson;
  bitbucket: BitbucketCredentialJson;
  slack: SlackCredentialJson;
  bookstack: BookstackCredentialJson;
  outline: OutlineCredentialJson;
  confluence: ConfluenceCredentialJson;
  jira: JiraCredentialJson;
  productboard: ProductboardCredentialJson;
  slab: SlabCredentialJson;
  coda: CodaCredentialJson;
  notion: NotionCredentialJson;
  guru: GuruCredentialJson;
  gong: GongCredentialJson;
  zulip: ZulipCredentialJson;
  linear: LinearCredentialJson;
  hubspot: HubSpotCredentialJson;
  document360: Document360CredentialJson;
  loopio: LoopioCredentialJson;
  box: BoxCredentialJson;
  dropbox: DropboxCredentialJson;
  salesforce: SalesforceCredentialJson;
  sharepoint: CredentialTemplateWithAuth<SharepointCredentialJson>;
  asana: AsanaCredentialJson;
  teams: CredentialTemplateWithAuth<TeamsCredentialJson>;
  outlook: CredentialTemplateWithAuth<OutlookCredentialJson>;
  zendesk: ZendeskCredentialJson;
  discourse: DiscourseCredentialJson;
  axero: AxeroCredentialJson;
  clickup: ClickupCredentialJson;
  s3: CredentialTemplateWithAuth<S3CredentialJson>;
  r2: R2CredentialJson;
  google_cloud_storage: GCSCredentialJson;
  oci_storage: OCICredentialJson;
  freshdesk: FreshdeskCredentialJson;
  fireflies: FirefliesCredentialJson;
  braintrust: BraintrustCredentialJson;
  canvas: CanvasCredentialJson;
  egnyte: EgnyteCredentialJson;
  airtable: AirtableCredentialJson;
  drupal_wiki: DrupalWikiCredentialJson;
  discord: DiscordCredentialJson;
  google_drive: Partial<GoogleDriveCredentialJson>;
  gmail: Partial<GmailCredentialJson>;
  gitbook: GitbookCredentialJson;
  highspot: HighspotCredentialJson;
  imap: ImapCredentialJson;
  testrail: TestRailCredentialJson;
};

export const credentialTemplates: Record<ValidSources, any> = {
  github: {
    github_access_token: "",
    github_base_url: null,
  },
  gitlab: {
    gitlab_url: "",
    gitlab_access_token: "",
  },
  lumapps: {
    lumapps_application_id: "",
    lumapps_api_key: "",
    lumapps_service_user: "",
  },
  bitbucket: {
    bitbucket_email: "",
    bitbucket_api_token: "",
  },
  slack: { slack_bot_token: "" },
  bookstack: {
    bookstack_base_url: "",
    bookstack_api_token_id: "",
    bookstack_api_token_secret: "",
  },
  outline: {
    outline_base_url: "",
    outline_api_token: "",
  },
  confluence: {
    confluence_username: "",
    confluence_access_token: "",
  },
  jira: {
    jira_user_email: null,
    jira_api_token: "",
  },
  productboard: { productboard_access_token: "" },
  slab: { slab_bot_token: "" },
  coda: { coda_bearer_token: "" },
  notion: { notion_integration_token: "" },
  guru: { guru_user: "", guru_user_token: "" },
  gong: {
    gong_access_key: "",
    gong_access_key_secret: "",
    gong_base_url: null,
  },
  zulip: { zuliprc_content: "" },
  linear: { linear_api_key: "" },
  hubspot: { hubspot_access_token: "" },
  document360: {
    portal_id: "",
    document360_api_token: "",
  },
  loopio: {
    loopio_subdomain: "",
    loopio_client_id: "",
    loopio_client_token: "",
  },
  box: {
    box_client_id: "",
    box_client_secret: "",
    box_enterprise_id: "",
    box_user_email: null,
  },
  dropbox: { dropbox_access_token: "" },
  salesforce: {
    sf_username: "",
    sf_password: "",
    sf_security_token: "",
    is_sandbox: false,
  },
  // SAFETY: the certificate template seeds sp_private_key with null, which TypedFile does not allow.
  sharepoint: {
    authentication_method: "client_credentials",
    authMethods: [
      {
        value: "client_secret",
        label: "Client Secret",
        fields: {
          sp_client_id: "",
          sp_client_secret: "",
          sp_directory_id: "",
        },
        description:
          "If you select this mode, the SharePoint connector will use a client secret to authenticate. You will need to provide the client ID and client secret.",
        disablePermSync: true,
      },
      {
        value: "certificate",
        label: "Certificate Authentication",
        fields: {
          sp_client_id: "",
          sp_directory_id: "",
          sp_certificate_password: "",
          sp_private_key: null,
        },
        description:
          "If you select this mode, the SharePoint connector will use a certificate to authenticate. You will need to provide the client ID, directory ID, certificate password, and PFX data.",
        disablePermSync: false,
      },
    ],
  } as CredentialTemplateWithAuth<SharepointCredentialJson>,
  asana: {
    asana_api_token_secret: "",
  },
  // SAFETY: the certificate template seeds teams_private_key with null, which TypedFile does not allow.
  teams: {
    authentication_method: "client_secret",
    authMethods: [
      {
        value: "client_secret",
        label: "Client Secret",
        fields: {
          teams_client_id: "",
          teams_client_secret: "",
          teams_directory_id: "",
        },
        description:
          "The connector signs in with a client secret of the app registration. Provide the client ID, directory ID and secret. Channel messages and members only: SharePoint refuses a secret, so Include Attachments needs the certificate option.",
      },
      {
        value: "certificate",
        label: "Certificate Authentication",
        fields: {
          teams_client_id: "",
          teams_directory_id: "",
          teams_certificate_password: "",
          teams_private_key: null,
        },
        description:
          "The connector signs in with a certificate uploaded to the app registration. Provide the client ID, directory ID, the PFX bundle and its password. Required for Include Attachments, which reads channel files and their readers from SharePoint.",
      },
    ],
  } as CredentialTemplateWithAuth<TeamsCredentialJson>,
  // SAFETY: the certificate template seeds outlook_private_key with null, which TypedFile does not allow.
  outlook: {
    authentication_method: "client_secret",
    authMethods: [
      {
        value: "client_secret",
        label: "Client Secret",
        fields: {
          outlook_client_id: "",
          outlook_client_secret: "",
          outlook_directory_id: "",
        },
        description:
          "The connector signs in with a client secret of the app registration. Provide the client ID, directory ID and secret.",
      },
      {
        value: "certificate",
        label: "Certificate Authentication",
        fields: {
          outlook_client_id: "",
          outlook_directory_id: "",
          outlook_certificate_password: "",
          outlook_private_key: null,
        },
        description:
          "The connector signs in with a certificate uploaded to the app registration. Provide the client ID, directory ID, the PFX bundle and its password.",
      },
    ],
  } as CredentialTemplateWithAuth<OutlookCredentialJson>,
  zendesk: {
    zendesk_subdomain: "",
    zendesk_email: "",
    zendesk_token: "",
  },
  discourse: {
    discourse_api_key: "",
    discourse_api_username: "",
  },
  axero: {
    base_url: "",
    axero_api_token: "",
  },
  clickup: {
    clickup_api_token: "",
    clickup_team_id: "",
  },

  s3: {
    authentication_method: "access_key",
    authMethods: [
      {
        value: "access_key",
        label: "Access Key and Secret",
        fields: {
          aws_access_key_id: "",
          aws_secret_access_key: "",
        },
        disablePermSync: false,
      },
      {
        value: "iam_role",
        label: "IAM Role",
        fields: {
          aws_role_arn: "",
        },
        disablePermSync: false,
      },
      {
        value: "assume_role",
        label: "Assume Role",
        fields: {},
        description:
          "If you select this mode, the Amazon EC2 instance will assume its existing role to access S3. No additional credentials are required.",
        disablePermSync: false,
      },
    ],
  },
  r2: {
    account_id: "",
    r2_access_key_id: "",
    r2_secret_access_key: "",
  },
  google_cloud_storage: {
    access_key_id: "",
    secret_access_key: "",
  },
  oci_storage: {
    namespace: "",
    region: "",
    access_key_id: "",
    secret_access_key: "",
  },
  freshdesk: {
    freshdesk_domain: "",
    freshdesk_api_key: "",
  },
  fireflies: {
    fireflies_api_key: "",
  },
  braintrust: {
    braintrust_api_key: "",
  },
  canvas: {
    canvas_access_token: "",
  },
  egnyte: {
    domain: "",
    access_token: "",
  },
  airtable: {
    airtable_access_token: "",
  },
  drupal_wiki: {
    drupal_wiki_api_token: "",
  },
  xenforo: null,
  google_sites: null,
  file: null,
  user_file: null,
  craft_file: null, // User Library - managed through dedicated UI
  wikipedia: null,
  mediawiki: null,
  web: null,
  not_applicable: null,
  ingestion_api: null,
  federated_slack: null,
  discord: { discord_bot_token: "" },

  // NOTE: These are Special Cases
  google_drive: { google_tokens: "" },
  gmail: { google_tokens: "" },
  gitbook: {
    gitbook_api_key: "",
  },
  highspot: {
    highspot_url: "",
    highspot_key: "",
    highspot_secret: "",
  },
  imap: {
    imap_username: "",
    imap_password: "",
  },
  testrail: {
    testrail_base_url: "",
    testrail_username: "",
    testrail_api_key: "",
  },
} satisfies CredentialTemplateMap;

export const credentialDisplayNames: Record<string, string> = {
  // Github
  github_access_token: "GitHub Access Token",
  github_base_url:
    "GitHub Enterprise Server URL (optional; set your server host like https://github.example.com, leave blank for github.com)",

  // LumApps
  lumapps_application_id: "LumApps Application ID",
  lumapps_api_key: "LumApps API Key",
  lumapps_service_user: "Service User Email (to index on behalf of)",

  // Gitlab
  gitlab_url: "GitLab URL",
  gitlab_access_token: "GitLab Access Token",

  // Bookstack
  bookstack_base_url: "Bookstack Base URL",
  bookstack_api_token_id: "Bookstack API Token ID",
  bookstack_api_token_secret: "Bookstack API Token Secret",

  // Outline
  outline_base_url:
    "Outline Base URL (e.g. https://app.getoutline.com or your self-hosted URL)",
  outline_api_token: "Outline API Token",

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

  // Coda
  coda_bearer_token: "Coda Bearer Token",

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
  gong_base_url:
    "Gong API Base URL (optional; set your region-specific host like https://<region>.api.gong.io for non-US data residency)",

  // Loopio
  loopio_subdomain: "Loopio Subdomain",
  loopio_client_id: "Loopio Client ID",
  loopio_client_token: "Loopio Client Token",

  // Linear
  linear_api_key: "Linear API Key",

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

  // Box
  box_client_id: "Box Client ID",
  box_client_secret: "Box Client Secret",
  box_enterprise_id: "Box Enterprise ID",
  box_user_email: "Email of Box user to impersonate (optional)",

  // Dropbox
  dropbox_access_token: "Dropbox API Key",

  // R2
  account_id: "R2 Account ID",
  r2_access_key_id: "R2 Access Key ID",
  r2_secret_access_key: "R2 Secret Access Key",

  // IMAP
  imap_username: "IMAP Username",
  imap_password: "IMAP Password",

  // TestRail
  testrail_base_url: "TestRail Base URL (e.g. https://yourcompany.testrail.io)",
  testrail_username: "TestRail Username or Email",
  testrail_api_key: "TestRail API Key",

  // S3
  aws_access_key_id: "AWS Access Key ID",
  aws_secret_access_key: "AWS Secret Access Key",
  aws_role_arn: "AWS Role ARN",
  authentication_method: "Authentication Method",

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
  is_sandbox: "Is Sandbox Environment",

  // Sharepoint
  sp_client_id: "SharePoint Client ID",
  sp_client_secret: "SharePoint Client Secret",
  sp_directory_id: "SharePoint Directory ID",
  sp_certificate_password: "SharePoint Certificate Password",
  sp_private_key: "SharePoint Private Key",

  // Asana
  asana_api_token_secret: "Asana API Token",

  // Teams
  teams_client_id: "Microsoft Teams Client ID",
  teams_client_secret: "Microsoft Teams Client Secret",
  teams_directory_id: "Microsoft Teams Directory ID",
  teams_certificate_password: "Microsoft Teams Certificate Password",
  teams_private_key: "Microsoft Teams Private Key (PFX)",

  // Outlook
  outlook_client_id: "Microsoft Outlook Client ID",
  outlook_client_secret: "Microsoft Outlook Client Secret",
  outlook_directory_id: "Microsoft Outlook Directory ID",
  outlook_certificate_password: "Microsoft Outlook Certificate Password",
  outlook_private_key: "Microsoft Outlook Private Key (PFX)",

  // Discourse
  discourse_api_key: "Discourse API Key",
  discourse_api_username: "Discourse API Username",

  // Axero
  base_url: "Axero Base URL",
  axero_api_token: "Axero API Token",

  // Freshdesk
  freshdesk_domain: "Freshdesk Domain",
  freshdesk_api_key: "Freshdesk API Key",

  // Fireflies
  fireflies_api_key: "Fireflies API Key",

  // Braintrust
  braintrust_api_key: "Braintrust API Key",

  // Canvas
  canvas_access_token: "Canvas Access Token",

  // GitBook
  gitbook_space_id: "GitBook Space ID",
  gitbook_api_key: "GitBook API Key",

  //Highspot
  highspot_url: "Highspot URL",
  highspot_key: "Highspot Key",
  highspot_secret: "Highspot Secret",

  // Drupal Wiki
  drupal_wiki_api_token: "Drupal Wiki Personal Access Token",

  // Bitbucket
  bitbucket_email: "Bitbucket Account Email",
  bitbucket_api_token: "Bitbucket API Token",
};
