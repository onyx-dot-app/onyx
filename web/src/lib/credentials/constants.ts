import type { ValidSources } from "@/lib/connectors/types/source";
import { FileTypeCategory } from "@/lib/connectors/types/fileTypes";
import type {
  CredentialDisplayName,
  CredentialFieldOptions,
  CredentialHint,
  CredentialJsonOf,
  CredentialMethodDescription,
  CredentialMethodLabel,
  CredentialSpec,
  CredentialSpecFields,
  CredentialTextKind,
  DefinedCredentialSpec,
  MethodsOf,
} from "@/lib/credentials/types";

/** Checks that each method only names fields the spec declares. */
function defineCredentialSpec<
  const TFields extends CredentialSpecFields,
  const TMethods extends MethodsOf<TFields> | undefined = undefined,
>(spec: {
  brandName: string;
  fields: TFields;
  methods?: TMethods;
}): DefinedCredentialSpec<TFields, TMethods> {
  // SAFETY: an omitted `methods` leaves TMethods at its `undefined` default.
  return { ...spec, methods: spec.methods as TMethods };
}

// ---------------------------------------------------------------------------
// Field builders
// ---------------------------------------------------------------------------

function textField<
  const TKind extends CredentialTextKind,
  const TOptions extends CredentialFieldOptions = {},
>(kind: TKind, displayName: CredentialDisplayName, options?: TOptions) {
  return Object.assign({ kind, displayName }, options);
}

function text<const TOptions extends CredentialFieldOptions = {}>(
  displayName: CredentialDisplayName,
  options?: TOptions
) {
  return textField("text", displayName, options);
}

function email<const TOptions extends CredentialFieldOptions = {}>(
  displayName: CredentialDisplayName,
  options?: TOptions
) {
  return textField("email", displayName, options);
}

function url<const TOptions extends CredentialFieldOptions = {}>(
  displayName: CredentialDisplayName,
  options?: TOptions
) {
  return textField("url", displayName, options);
}

function secret<const TOptions extends CredentialFieldOptions = {}>(
  displayName: CredentialDisplayName,
  options?: TOptions
) {
  return textField("secret", displayName, options);
}

function toggle(displayName: CredentialDisplayName) {
  return { kind: "toggle", displayName } as const;
}

function checkbox<const TOptions extends CredentialFieldOptions = {}>(
  displayName: CredentialDisplayName,
  options?: TOptions
) {
  return Object.assign({ kind: "checkbox" as const, displayName }, options);
}

function file<const TOptions extends CredentialFieldOptions = {}>(
  displayName: CredentialDisplayName,
  fileType: FileTypeCategory,
  options?: TOptions
) {
  return Object.assign(
    { kind: "file" as const, displayName, fileType },
    options
  );
}

// ---------------------------------------------------------------------------
// Family factories
// ---------------------------------------------------------------------------

type MicrosoftAppFields<TPrefix extends string> = {
  [K in `${TPrefix}_client_id` | `${TPrefix}_directory_id`]: ReturnType<
    typeof text
  >;
} & {
  [K in
    | `${TPrefix}_client_secret`
    | `${TPrefix}_certificate_password`]: ReturnType<typeof secret>;
} & {
  [K in `${TPrefix}_private_key`]: ReturnType<typeof file>;
};

interface MicrosoftAppSpecOptions {
  brandName: string;
  fileType: FileTypeCategory;
  privateKeyDisplayName: CredentialDisplayName;
  privateKeyHint?: CredentialHint;
  certificateLabel: CredentialMethodLabel;
  descriptions?: {
    clientSecret: CredentialMethodDescription;
    certificate: CredentialMethodDescription;
  };
  /** A client secret cannot read permissions, so it hides Auto Sync. */
  clientSecretDisablesPermSync?: boolean;
}

/**
 * A Microsoft app registration (SharePoint, OneDrive, Outlook, Teams): a
 * client id and directory id, plus either a client secret or a PFX
 * certificate. Keys take the source's prefix, like `sp_client_id`.
 */
function microsoftAppSpec<const TPrefix extends string>(
  prefix: TPrefix,
  options: MicrosoftAppSpecOptions
): DefinedCredentialSpec<
  MicrosoftAppFields<TPrefix>,
  MethodsOf<MicrosoftAppFields<TPrefix>>
> {
  const key = <TName extends string>(name: TName) =>
    `${prefix}_${name}` as const;
  // SAFETY: computed keys widen to `string`; these are exactly the keys of
  // MicrosoftAppFields<TPrefix>.
  const fields = {
    [key("client_id")]: text("clientId"),
    [key("directory_id")]: text("directoryId"),
    [key("client_secret")]: secret("clientSecret"),
    [key("certificate_password")]: secret("certificatePassword"),
    [key("private_key")]: file(
      options.privateKeyDisplayName,
      options.fileType,
      options.privateKeyHint ? { hint: options.privateKeyHint } : {}
    ),
  } as MicrosoftAppFields<TPrefix>;

  return {
    brandName: options.brandName,
    fields,
    methods: [
      {
        value: "client_secret",
        label: "clientSecret",
        description: options.descriptions?.clientSecret,
        fields: [key("client_id"), key("directory_id"), key("client_secret")],
        disablePermSync: options.clientSecretDisablesPermSync,
      },
      {
        value: "certificate",
        label: options.certificateLabel,
        description: options.descriptions?.certificate,
        fields: [
          key("client_id"),
          key("directory_id"),
          key("certificate_password"),
          key("private_key"),
        ],
      },
    ],
  };
}

/**
 * The credential each source asks for. Field keys are the exact
 * `credential_json` keys the backend reads. A source with no credential, or
 * one whose credential is set up elsewhere, maps to `null`.
 */
export const CREDENTIAL_SPECS = {
  github: defineCredentialSpec({
    brandName: "GitHub",
    fields: {
      github_access_token: secret("apiToken"),
      github_base_url: url("enterpriseServerUrl", {
        optional: true,
        hint: { key: "githubBaseUrl" },
      }),
    },
  }),
  gitlab: defineCredentialSpec({
    brandName: "GitLab",
    fields: {
      gitlab_url: url("url"),
      gitlab_access_token: secret("apiToken"),
    },
  }),
  lumapps: defineCredentialSpec({
    brandName: "LumApps",
    fields: {
      lumapps_application_id: text("applicationId"),
      lumapps_api_key: secret("apiToken"),
      lumapps_service_user: email("serviceUserEmail", {
        hint: { key: "lumappsServiceUser" },
      }),
    },
  }),
  bitbucket: defineCredentialSpec({
    brandName: "Bitbucket",
    fields: {
      bitbucket_email: email("accountEmail"),
      bitbucket_api_token: secret("apiToken"),
    },
  }),
  slack: defineCredentialSpec({
    brandName: "Slack",
    fields: { slack_bot_token: secret("botToken") },
  }),
  bookstack: defineCredentialSpec({
    brandName: "Bookstack",
    fields: {
      bookstack_base_url: url("baseUrl"),
      bookstack_api_token_id: text("apiTokenId"),
      bookstack_api_token_secret: secret("apiTokenSecret"),
    },
  }),
  outline: defineCredentialSpec({
    brandName: "Outline",
    fields: {
      outline_base_url: url("baseUrl", { hint: { key: "outlineBaseUrl" } }),
      outline_api_token: secret("apiToken"),
    },
  }),
  confluence: defineCredentialSpec({
    brandName: "Confluence",
    fields: {
      confluence_username: email("accountEmail"),
      confluence_access_token: secret("apiToken"),
    },
  }),
  jira: defineCredentialSpec({
    brandName: "Jira",
    fields: {
      jira_user_email: email("accountEmail", {
        optional: true,
        hint: { key: "jiraUserEmail" },
      }),
      jira_api_token: secret("apiToken"),
    },
  }),
  productboard: defineCredentialSpec({
    brandName: "Productboard",
    fields: { productboard_access_token: secret("apiToken") },
  }),
  jsm: defineCredentialSpec({
    brandName: "Jira Service Management",
    fields: {
      jira_user_email: email("accountEmail", {
        optional: true,
        hint: { key: "jiraUserEmail" },
      }),
      jira_api_token: secret("apiToken"),
    },
  }),
  slab: defineCredentialSpec({
    brandName: "Slab",
    fields: { slab_bot_token: secret("botToken") },
  }),
  coda: defineCredentialSpec({
    brandName: "Coda",
    fields: { coda_bearer_token: secret("apiToken") },
  }),
  notion: defineCredentialSpec({
    brandName: "Notion",
    fields: { notion_integration_token: secret("integrationToken") },
  }),
  guru: defineCredentialSpec({
    brandName: "Guru",
    fields: {
      guru_user: email("accountEmail"),
      guru_user_token: secret("apiToken"),
    },
  }),
  gong: defineCredentialSpec({
    brandName: "Gong",
    fields: {
      gong_access_key: text("accessKey"),
      gong_access_key_secret: secret("accessKeySecret"),
      gong_base_url: url("apiBaseUrl", {
        optional: true,
        hint: { key: "gongBaseUrl" },
      }),
    },
  }),
  zulip: defineCredentialSpec({
    brandName: "Zulip",
    fields: { zuliprc_content: secret("zuliprcContent") },
  }),
  linear: defineCredentialSpec({
    brandName: "Linear",
    fields: { linear_api_key: secret("apiToken") },
  }),
  hubspot: defineCredentialSpec({
    brandName: "HubSpot",
    fields: { hubspot_access_token: secret("apiToken") },
  }),
  document360: defineCredentialSpec({
    brandName: "Document360",
    fields: {
      portal_id: text("portalId"),
      document360_api_token: secret("apiToken"),
    },
  }),
  loopio: defineCredentialSpec({
    brandName: "Loopio",
    fields: {
      loopio_subdomain: text("subdomain"),
      loopio_client_id: text("clientId"),
      loopio_client_token: secret("clientToken"),
    },
  }),
  box: defineCredentialSpec({
    brandName: "Box",
    fields: {
      box_client_id: text("clientId"),
      box_client_secret: secret("clientSecret"),
      box_enterprise_id: text("enterpriseId"),
      box_user_email: email("userEmail", {
        optional: true,
        hint: { key: "boxUserEmail" },
      }),
    },
  }),
  dropbox: defineCredentialSpec({
    brandName: "Dropbox",
    fields: { dropbox_access_token: secret("apiToken") },
  }),
  salesforce: defineCredentialSpec({
    brandName: "Salesforce",
    fields: {
      sf_username: text("username"),
      sf_password: secret("password"),
      sf_security_token: secret("securityToken"),
      is_sandbox: toggle("isSandbox"),
    },
  }),
  sharepoint: microsoftAppSpec("sp", {
    brandName: "SharePoint",
    fileType: FileTypeCategory.SHAREPOINT_PFX_FILE,
    privateKeyDisplayName: "privateKey",
    certificateLabel: "certificateAuthentication",
    descriptions: {
      clientSecret: "sharepointClientSecret",
      certificate: "sharepointCertificate",
    },
    clientSecretDisablesPermSync: true,
  }),
  onedrive: microsoftAppSpec("onedrive", {
    brandName: "OneDrive",
    fileType: FileTypeCategory.ONEDRIVE_PFX_FILE,
    privateKeyDisplayName: "certificate",
    certificateLabel: "certificate",
  }),
  asana: defineCredentialSpec({
    brandName: "Asana",
    fields: { asana_api_token_secret: secret("apiToken") },
  }),
  // The same PFX rules apply to every Microsoft app registration.
  teams: microsoftAppSpec("teams", {
    brandName: "Microsoft Teams",
    fileType: FileTypeCategory.SHAREPOINT_PFX_FILE,
    privateKeyDisplayName: "privateKey",
    privateKeyHint: { key: "pfxFile" },
    certificateLabel: "certificateAuthentication",
    descriptions: {
      clientSecret: "teamsClientSecret",
      certificate: "teamsCertificate",
    },
  }),
  outlook: microsoftAppSpec("outlook", {
    brandName: "Microsoft Outlook",
    fileType: FileTypeCategory.SHAREPOINT_PFX_FILE,
    privateKeyDisplayName: "privateKey",
    privateKeyHint: { key: "pfxFile" },
    certificateLabel: "certificateAuthentication",
    descriptions: {
      clientSecret: "outlookClientSecret",
      certificate: "outlookCertificate",
    },
  }),
  zendesk: defineCredentialSpec({
    brandName: "Zendesk",
    fields: {
      zendesk_subdomain: text("subdomain"),
      zendesk_email: email("accountEmail"),
      zendesk_token: secret("apiToken"),
    },
  }),
  discourse: defineCredentialSpec({
    brandName: "Discourse",
    fields: {
      discourse_api_key: secret("apiToken"),
      discourse_api_username: text("apiUsername"),
    },
  }),
  axero: defineCredentialSpec({
    brandName: "Axero",
    fields: {
      base_url: url("baseUrl"),
      axero_api_token: secret("apiToken"),
    },
  }),
  clickup: defineCredentialSpec({
    brandName: "ClickUp",
    fields: {
      clickup_api_token: secret("apiToken"),
      clickup_team_id: text("teamId"),
    },
  }),
  s3: defineCredentialSpec({
    brandName: "AWS",
    fields: {
      aws_access_key_id: text("accessKeyId"),
      aws_secret_access_key: secret("secretAccessKey"),
      aws_role_arn: text("roleArn"),
    },
    methods: [
      {
        value: "access_key",
        label: "accessKeyAndSecret",
        fields: ["aws_access_key_id", "aws_secret_access_key"],
      },
      { value: "iam_role", label: "iamRole", fields: ["aws_role_arn"] },
      {
        value: "assume_role",
        label: "assumeRole",
        description: "s3AssumeRole",
        fields: [],
      },
    ],
  }),
  r2: defineCredentialSpec({
    brandName: "R2",
    fields: {
      account_id: text("accountId"),
      r2_access_key_id: text("accessKeyId"),
      r2_secret_access_key: secret("secretAccessKey"),
    },
  }),
  google_cloud_storage: defineCredentialSpec({
    brandName: "GCS",
    fields: {
      access_key_id: text("accessKeyId"),
      secret_access_key: secret("secretAccessKey"),
    },
  }),
  oci_storage: defineCredentialSpec({
    brandName: "OCI",
    fields: {
      namespace: text("namespace"),
      region: text("region"),
      access_key_id: text("accessKeyId"),
      secret_access_key: secret("secretAccessKey"),
    },
  }),
  freshdesk: defineCredentialSpec({
    brandName: "Freshdesk",
    fields: {
      freshdesk_domain: text("domain"),
      freshdesk_api_key: secret("apiToken"),
    },
  }),
  fireflies: defineCredentialSpec({
    brandName: "Fireflies",
    fields: { fireflies_api_key: secret("apiToken") },
  }),
  zoom: defineCredentialSpec({
    brandName: "Zoom",
    fields: {
      zoom_account_id: text("accountId"),
      zoom_client_id: text("clientId"),
      zoom_client_secret: secret("clientSecret"),
    },
  }),
  braintrust: defineCredentialSpec({
    brandName: "Braintrust",
    fields: { braintrust_api_key: secret("apiToken") },
  }),
  canvas: defineCredentialSpec({
    brandName: "Canvas",
    fields: { canvas_access_token: secret("apiToken") },
  }),
  egnyte: defineCredentialSpec({
    brandName: "Egnyte",
    fields: {
      domain: text("domain"),
      access_token: secret("apiToken"),
    },
  }),
  airtable: defineCredentialSpec({
    brandName: "Airtable",
    fields: { airtable_access_token: secret("apiToken") },
  }),
  drupal_wiki: defineCredentialSpec({
    brandName: "Drupal Wiki",
    fields: { drupal_wiki_api_token: secret("apiToken") },
  }),
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
  discord: defineCredentialSpec({
    brandName: "Discord",
    fields: { discord_bot_token: secret("botToken") },
  }),
  // Gmail and Google Drive set up their credentials on their own pages.
  google_drive: defineCredentialSpec({
    brandName: "Google",
    fields: { google_tokens: secret("oauthTokens") },
  }),
  gmail: defineCredentialSpec({
    brandName: "Google",
    fields: { google_tokens: secret("oauthTokens") },
  }),
  gitbook: defineCredentialSpec({
    brandName: "GitBook",
    fields: { gitbook_api_key: secret("apiToken") },
  }),
  highspot: defineCredentialSpec({
    brandName: "Highspot",
    fields: {
      highspot_url: url("url"),
      highspot_key: text("key"),
      highspot_secret: secret("secret"),
    },
  }),
  imap: defineCredentialSpec({
    brandName: "IMAP",
    fields: {
      imap_username: text("username"),
      imap_password: secret("password"),
    },
  }),
  testrail: defineCredentialSpec({
    brandName: "TestRail",
    fields: {
      testrail_base_url: url("baseUrl", { hint: { key: "testrailBaseUrl" } }),
      testrail_username: email("accountEmail"),
      testrail_api_key: secret("apiToken"),
    },
  }),
} as const satisfies Record<ValidSources, CredentialSpec | null>;

/** The `credential_json` of one source, read from its spec. */
export type SourceCredentialJson<
  TSource extends keyof typeof CREDENTIAL_SPECS,
> = CredentialJsonOf<(typeof CREDENTIAL_SPECS)[TSource]>;
