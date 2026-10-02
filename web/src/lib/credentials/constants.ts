import { ValidSources } from "@/lib/connectors/types/source";
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
  OneDriveAuthenticationMethod,
  OneDriveCredentialJson,
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
  ZoomCredentialJson,
  ZulipCredentialJson,
} from "@/lib/credentials/types";

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
  onedrive: CredentialTemplateWithAuth<
    OneDriveCredentialJson,
    OneDriveAuthenticationMethod
  >;
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
  zoom: ZoomCredentialJson;
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

export const CREDENTIAL_TEMPLATES: Record<ValidSources, any> = {
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
  onedrive: {
    authentication_method: "client_secret",
    authMethods: [
      {
        value: "client_secret",
        label: "Client Secret",
        fields: {
          onedrive_client_id: "",
          onedrive_directory_id: "",
          onedrive_client_secret: "",
        },
      },
      {
        value: "certificate",
        label: "Certificate",
        fields: {
          onedrive_client_id: "",
          onedrive_directory_id: "",
          onedrive_certificate_password: "",
          onedrive_private_key: null,
        },
      },
    ],
  } satisfies CredentialTemplateWithAuth<
    OneDriveCredentialJson,
    OneDriveAuthenticationMethod
  >,
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
  zoom: {
    zoom_account_id: "",
    zoom_client_id: "",
    zoom_client_secret: "",
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
