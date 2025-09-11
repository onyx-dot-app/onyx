import * as Yup from "yup";
import { IsPublicGroupSelectorFormType } from "@/components/IsPublicGroupSelector";
import { ConfigurableSources, ValidInputTypes, ValidSources } from "../types";
import { AccessTypeGroupSelectorFormType } from "@/components/admin/connectors/AccessTypeGroupSelector";
import { Credential } from "@/lib/connectors/credentials"; // Import Credential type
import i18n from "@/i18n/init";
import k from "../../i18n/keys";

export function isLoadState(connector_name: string): boolean {
  // TODO: centralize connector metadata like this somewhere instead of hardcoding it here
  const loadStateConnectors = ["web", "xenforo", "file", "airtable"];
  if (loadStateConnectors.includes(connector_name)) {
    return true;
  }

  return false;
}

export type InputType =
  | "list"
  | "text"
  | "select"
  | "multiselect"
  | "boolean"
  | "number"
  | "file";

export type StringWithDescription = {
  value: string;
  name: string;
  description?: string;
};

export interface Option {
  label: string | ((currentCredential: Credential<any> | null) => string);
  name: string;
  description?:
    | string
    | ((currentCredential: Credential<any> | null) => string);
  query?: string;
  optional?: boolean;
  hidden?: boolean;
  visibleCondition?: (
    values: any,
    currentCredential: Credential<any> | null
  ) => boolean;
  wrapInCollapsible?: boolean;
  disabled?: boolean | ((currentCredential: Credential<any> | null) => boolean);
}

export interface SelectOption extends Option {
  type: "select";
  options?: StringWithDescription[];
  default?: string;
}

export interface ListOption extends Option {
  type: "list";
  default?: string[];
  transform?: (values: string[]) => string[];
}

export interface TextOption extends Option {
  type: "text";
  default?: string;
  initial?: string | ((currentCredential: Credential<any> | null) => string);
  isTextArea?: boolean;
}

export interface NumberOption extends Option {
  type: "number";
  default?: number;
}

export interface BooleanOption extends Option {
  type: "checkbox";
  default?: boolean;
}

export interface FileOption extends Option {
  type: "file";
  default?: string;
}

export interface StringTabOption extends Option {
  type: "string_tab";
  default?: string;
}

export interface TabOption extends Option {
  type: "tab";
  defaultTab?: string;
  tabs: {
    label: string;
    value: string;
    fields: (
      | BooleanOption
      | ListOption
      | TextOption
      | NumberOption
      | SelectOption
      | FileOption
      | StringTabOption
    )[];
  }[];
  default?: [];
}

export interface ConnectionConfiguration {
  description: string;
  subtext?: string;
  initialConnectorName?: string; // a key in the credential to prepopulate the connector name field
  values: (
    | BooleanOption
    | ListOption
    | TextOption
    | NumberOption
    | SelectOption
    | FileOption
    | TabOption
  )[];

  advanced_values: (
    | BooleanOption
    | ListOption
    | TextOption
    | NumberOption
    | SelectOption
    | FileOption
    | TabOption
  )[];

  overrideDefaultFreq?: number;
}

export const connectorConfigs: Record<
  ConfigurableSources,
  ConnectionConfiguration
> = {
  web: {
    description: i18n.t(k.CONFIGURE_WEB_CONNECTOR),
    values: [
      {
        type: "text",
        query: i18n.t(k.ENTER_WEBSITE_URL_FOR_CRAWLING),
        label: "URL",
        name: "base_url",
        optional: false,
      },
      {
        type: "select",
        query: i18n.t(k.SELECT_WEB_CONNECTOR_TYPE),
        label: i18n.t(k.COLLECTION_METHOD),
        name: "web_connector_type",
        options: [
          { name: i18n.t(k.RECURSIVE), value: "recursive" },
          { name: i18n.t(k.SINGLE), value: "single" },
          { name: "sitemap", value: "sitemap" },
        ],
      },
    ],
    advanced_values: [],
    overrideDefaultFreq: 60 * 60 * 24,
  },
  bookstack: {
    description: i18n.t(k.CONFIGURE_BOOKSTACK_CONNECTOR),
    values: [],
    advanced_values: [],
  },
  confluence: {
    description: i18n.t(k.CONFIGURE_CONFLUENCE_CONNECTOR),
    values: [
      {
        type: "checkbox",
        query: i18n.t(k.IS_CONFLUENCE_CLOUD),
        label: i18n.t(k.CLOUD),
        name: "is_cloud",
        optional: false,
        default: true,
        description: i18n.t(k.CHECK_IF_CONFLUENCE_CLOUD),
      },
      {
        type: "text",
        query: i18n.t(k.ENTER_WIKI_URL),
        label: "Wiki URL",
        name: "wiki_base",
        optional: false,
        description: i18n.t(k.CONFLUENCE_URL_EXAMPLE),
      },
      {
        type: "tab",
        name: "indexing_scope",
        label: i18n.t(k.HOW_TO_INDEX_CONFLUENCE),
        optional: true,
        tabs: [
          {
            value: "everything",
            label: i18n.t(k.ALL),
            fields: [
              {
                type: "string_tab",
                label: i18n.t(k.ALL),
                name: "everything",
                description: i18n.t(k.CONNECTOR_WILL_INDEX_ALL_PAGES),
              },
            ],
          },
          {
            value: "space",
            label: i18n.t(k.SPACE),
            fields: [
              {
                type: "text",
                query: i18n.t(k.ENTER_SPACE),
                label: i18n.t(k.SPACE_KEY),
                name: "space",
                default: "",
                description: i18n.t(k.CONFLUENCE_SPACE_KEY_EXAMPLE),
              },
            ],
          },
          {
            value: "page",
            label: i18n.t(k.PAGE),
            fields: [
              {
                type: "text",
                query: i18n.t(k.ENTER_PAGE_ID),
                label: i18n.t(k.PAGE_ID),
                name: "page_id",
                default: "",
                description: i18n.t(k.SPECIFIC_PAGE_ID_FOR_INDEXING),
              },
              {
                type: "checkbox",
                query: i18n.t(k.SHOULD_INDEX_PAGES_RECURSIVELY),
                label: i18n.t(k.INDEX_RECURSIVELY),
                name: "index_recursively",
                description: i18n.t(k.INDEX_PAGE_AND_CHILDREN_DESCRIPTION),
                optional: false,
                default: true,
              },
            ],
          },
          {
            value: "cql",
            label: i18n.t(k.CQL_QUERY),
            fields: [
              {
                type: "text",
                query: i18n.t(k.ENTER_CQL_QUERY_OPTIONAL),
                label: i18n.t(k.CQL_QUERY_LABEL),
                name: "cql_query",
                default: "",
                description: i18n.t(k.CQL_QUERY_IMPORTANT_NOTE),
              },
            ],
          },
        ],
        defaultTab: "space",
      },
    ],
    advanced_values: [],
  },
  jira: {
    description: i18n.t(k.CONFIGURE_JIRA_CONNECTOR),
    subtext: i18n.t(k.JIRA_CONNECTOR_DESCRIPTION),
    values: [
      {
        type: "text",
        query: i18n.t(k.ENTER_JIRA_PROJECT_URL),
        label: i18n.t(k.JIRA_PROJECT_URL_LABEL),
        name: "jira_project_url",
        optional: false,
      },
      {
        type: "list",
        query: i18n.t(k.ENTER_EMAIL_ADDRESSES_FOR_COMMENT_BLACKLIST),
        label: i18n.t(k.COMMENT_BLACKLIST_LABEL),
        name: "comment_email_blacklist",
        description: i18n.t(k.COMMENT_BLACKLIST_DESCRIPTION),
        optional: true,
      },
    ],
    advanced_values: [],
  },
  redmine: {
    description: i18n.t(k.CONFIGURE_REDMINE_CONNECTOR),
    subtext: i18n.t(k.REDMINE_CONNECTOR_DESCRIPTION),
    values: [
      {
        type: "text",
        query: i18n.t(k.ENTER_REDMINE_PROJECT_URL),
        label: i18n.t(k.REDMINE_NAME_LABEL),
        name: "redmine_project_url",
        optional: false,
      },
      {
        type: "list",
        query: i18n.t(k.ENTER_EMAIL_ADDRESSES_FOR_COMMENT_BLACKLIST),
        label: i18n.t(k.COMMENT_BLACKLIST_LABEL),
        name: "comment_email_blacklist",
        description: i18n.t(k.COMMENT_BLACKLIST_DESCRIPTION),
        optional: true,
      },
    ],
    advanced_values: [],
  },
  bitrix: {
    description: i18n.t(k.CONFIGURE_BITRIX_CONNECTOR),
    subtext: i18n.t(k.BITRIX_CONNECTOR_DESCRIPTION),
    values: [
      {
        type: "text",
        query: i18n.t(k.ENTER_BITRIX_PROJECT_URL),
        label: i18n.t(k.BITRIX_NAME_LABEL),
        name: "bitrix_project_url",
        optional: false,
      },
      {
        type: "list",
        query: i18n.t(k.ENTER_EMAIL_ADDRESSES_FOR_COMMENT_BLACKLIST),
        label: i18n.t(k.COMMENT_BLACKLIST_LABEL),
        name: "comment_email_blacklist",
        description: i18n.t(k.COMMENT_BLACKLIST_DESCRIPTION),
        optional: true,
      },
    ],
    advanced_values: [],
  },
  file: {
    description: i18n.t(k.FILE_CONNECTOR_CONFIGURATION),
    values: [
      {
        type: "file",
        query: i18n.t(k.ENTER_FILE_LOCATION),
        label: i18n.t(k.FILE_LOCATION_LABEL),
        name: "file_locations",
        optional: false,
      },
    ],
    advanced_values: [],
  },
  notion: {
    description: i18n.t(k.CONFIGURE_NOTION_CONNECTOR),
    values: [
      {
        type: "text",
        query: i18n.t(k.ENTER_ROOT_PAGE_ID),
        label: i18n.t(k.ROOT_PAGE_ID_LABEL),
        name: "root_page_id",
        optional: true,
        description: i18n.t(k.ROOT_PAGE_ID_DESCRIPTION),
      },
    ],
    advanced_values: [],
  },
  github: {
    description: i18n.t(k.CONFIGURE_GITHUB_CONNECTOR),
    values: [
      {
        type: "text",
        query: i18n.t(k.ENTER_REPO_OWNER_QUERY),
        label: i18n.t(k.REPO_OWNER_LABEL),
        name: "repo_owner",
        optional: false,
      },
      {
        type: "text",
        query: i18n.t(k.ENTER_REPO_NAME_QUERY),
        label: i18n.t(k.REPO_NAME_LABEL),
        name: "repo_name",
        optional: false,
      },
      {
        type: "checkbox",
        query: i18n.t(k.ENABLE_PULL_REQUESTS_QUERY),
        label: i18n.t(k.ENABLE_PULL_REQUESTS_LABEL),
        description: i18n.t(k.INDEX_PULL_REQUESTS_DESCRIPTION),
        name: "include_prs",
        optional: true,
      },
      {
        type: "checkbox",
        query: i18n.t(k.ENABLE_ISSUES_QUERY),
        label: i18n.t(k.ENABLE_ISSUES_LABEL),
        name: "include_issues",
        description: i18n.t(k.INDEX_ISSUES_DESCRIPTION),
        optional: true,
      },
    ],
    advanced_values: [],
  },
  gitlab: {
    description: i18n.t(k.CONFIGURE_GITLAB_CONNECTOR),
    values: [
      {
        type: "text",
        query: i18n.t(k.ENTER_PROJECT_OWNER_QUERY),
        label: i18n.t(k.PROJECT_OWNER_LABEL),
        name: "project_owner",
        optional: false,
      },
      {
        type: "text",
        query: i18n.t(k.ENTER_PROJECT_NAME_QUERY),
        label: i18n.t(k.PROJECT_NAME_LABEL),
        name: "project_name",
        optional: false,
      },
      {
        type: "checkbox",
        query: i18n.t(k.ENABLE_MERGE_REQUESTS_QUERY),
        label: i18n.t(k.ENABLE_MRS_LABEL),
        name: "include_mrs",
        default: true,
        hidden: true,
      },
      {
        type: "checkbox",
        query: i18n.t(k.ENABLE_ISSUES_QUERY),
        label: i18n.t(k.ENABLE_ISSUES_LABEL),
        name: "include_issues",
        optional: true,
        hidden: true,
      },
    ],
    advanced_values: [],
  },
  gmail: {
    description: i18n.t(k.CONFIGURE_GMAIL_CONNECTOR),
    values: [],
    advanced_values: [],
  },
  sharepoint: {
    description: i18n.t(k.CONFIGURE_SHAREPOINT_CONNECTOR),
    values: [
      {
        type: "list",
        query: i18n.t(k.ENTER_SHAREPOINT_SITES),
        label: i18n.t(k.SITES_LABEL),
        name: "sites",
        optional: true,
        description: i18n.t(k.SHAREPOINT_SITES_DESCRIPTION),
      },
    ],
    advanced_values: [],
  },
  minio: {
    description: i18n.t(k.CONFIGURE_S3_CONNECTOR),
    values: [
      {
        type: "text",
        query: i18n.t(k.ENTER_BUCKET_NAME),
        label: i18n.t(k.BUCKET_NAME_LABEL),
        name: "bucket_name",
        optional: false,
      },
      {
        type: "text",
        query: i18n.t(k.ENTER_PREFIX),
        label: i18n.t(k.PREFIX_LABEL),
        name: "prefix",
        optional: true,
      },
      {
        type: "text",
        label: i18n.t(k.BUCKET_TYPE_LABEL),
        name: "bucket_type",
        optional: false,
        default: "minio",
        hidden: true,
      },
    ],
    advanced_values: [],
    overrideDefaultFreq: 60 * 60 * 24,
  },
  wikipedia: {
    description: i18n.t(k.CONFIGURE_WIKIPEDIA_CONNECTOR),
    values: [
      {
        type: "text",
        query: i18n.t(k.ENTER_LANGUAGE_CODE),
        label: i18n.t(k.LANGUAGE_CODE_LABEL),
        name: "language_code",
        optional: false,
        description: i18n.t(k.LANGUAGE_CODE_DESCRIPTION),
      },
      {
        type: "list",
        query: i18n.t(k.ENTER_CATEGORIES_TO_INCLUDE),
        label: i18n.t(k.CATEGORIES_FOR_INDEXING_LABEL),
        name: "categories",
        description: i18n.t(k.CATEGORIES_DESCRIPTION),
        optional: true,
      },
      {
        type: "list",
        query: i18n.t(k.ENTER_PAGES_TO_INCLUDE),
        label: i18n.t(k.PAGES_LABEL),
        name: "pages",
        optional: true,
        description: i18n.t(k.PAGES_DESCRIPTION),
      },
      {
        type: "number",
        query: i18n.t(k.ENTER_RECURSION_DEPTH),
        label: i18n.t(k.RECURSION_DEPTH_LABEL),
        name: "recurse_depth",
        description: i18n.t(k.RECURSION_DEPTH_DESCRIPTION),
        optional: false,
      },
    ],
    advanced_values: [],
  },
  yandex: {
    description: i18n.t(k.CONFIGURE_YANDEX_MAIL_CONNECTOR),
    values: [],
    advanced_values: [],
  },
  mailru: {
    description: i18n.t(k.CONFIGURE_MAILRU_CONNECTOR),
    values: [],
    advanced_values: [],
  },
  postgresql: {
    description: i18n.t(k.CONFIGURE_POSTGRESQL_CONNECTOR),
    values: [
      {
        type: "text",
        query: i18n.t(k.ENTER_SCHEMA),
        label: i18n.t(k.SCHEMA_LABEL),
        name: "schema",
        optional: true,
      },
      {
        type: "text",
        query: i18n.t(k.ENTER_TABLE),
        label: i18n.t(k.TABLE_LABEL),
        name: "table_name",
      },
      {
        type: "text",
        query: i18n.t(k.ENTER_COLUMNS_TEXT),
        label: i18n.t(k.TEXT_COLUMNS_LABEL),
        name: "conten_columns",
        optional: true,
      },
      {
        type: "text",
        query: i18n.t(k.ENTER_COLUMNS_METADATA),
        label: i18n.t(k.METADATA_COLUMNS_LABEL),
        name: "metadata_columns",
        optional: true,
      },
      {
        type: "text",
        query: i18n.t(k.ENTER_SQL_QUERY),
        label: i18n.t(k.SQL_QUERY_LABEL),
        name: "query",
        optional: true,
      },
    ],
    advanced_values: [],
  },
};
export function createConnectorInitialValues(
  connector: ConfigurableSources,
  currentCredential: Credential<any> | null = null
): Record<string, any> & AccessTypeGroupSelectorFormType {
  const configuration = connectorConfigs[connector];

  return {
    name: "",
    groups: [],
    access_type: "public",
    ...configuration.values.reduce((acc, field) => {
      if (field.type === "select") {
        acc[field.name] = null;
      } else if (field.type === "list") {
        acc[field.name] = field.default || [];
      } else if (field.type === "checkbox") {
        // Special case for include_files_shared_with_me when using service account
        if (
          field.name === "include_files_shared_with_me" &&
          currentCredential &&
          !currentCredential.credential_json?.google_tokens
        ) {
          acc[field.name] = true;
        } else {
          acc[field.name] = field.default || false;
        }
      } else if (field.default !== undefined) {
        acc[field.name] = field.default;
      }
      return acc;
    }, {} as { [record: string]: any }),
  };
}

export function createConnectorValidationSchema(
  connector: ConfigurableSources
): Yup.ObjectSchema<Record<string, any>> {
  const configuration = connectorConfigs[connector];

  const object = Yup.object().shape({
    access_type: Yup.string().required(i18n.t(k.ACCESS_TYPE_REQUIRED)),
    name: Yup.string().required(i18n.t(k.CONNECTOR_NAME_REQUIRED)),
    ...[...configuration.values, ...configuration.advanced_values].reduce(
      (acc, field) => {
        let schema: any =
          field.type === "select"
            ? Yup.string()
            : field.type === "list"
            ? Yup.array().of(Yup.string())
            : field.type === "checkbox"
            ? Yup.boolean()
            : field.type === "file"
            ? Yup.mixed()
            : Yup.string();

        if (!field.optional) {
          schema = schema.required(
            `${i18n.t(k.FIELD_REQUIRED)} ${field.label}`
          );
        }

        acc[field.name] = schema;
        return acc;
      },
      {} as Record<string, any>
    ),
    // These are advanced settings
    indexingStart: Yup.string().nullable(),
    pruneFreq: Yup.number().min(0, i18n.t(k.CHUNK_SIZE_MUST_BE_NON_NEGATIVE)),
    refreshFreq: Yup.number().min(
      0,
      i18n.t(k.REFRESH_FREQUENCY_MUST_BE_NON_NEGATIVE)
    ),
  });

  return object;
}

export const defaultPruneFreqDays = 30; // 30 days
export const defaultRefreshFreqMinutes = 30; // 30 minutes

// CONNECTORS
export interface ConnectorBase<T> {
  name: string;
  source: ValidSources;
  input_type: ValidInputTypes;
  connector_specific_config: T;
  refresh_freq: number | null;
  prune_freq: number | null;
  indexing_start: Date | null;
  access_type: string;
  groups?: number[];
  from_beginning?: boolean;
}

export interface Connector<T> extends ConnectorBase<T> {
  id: number;
  credential_ids: number[];
  time_created: string;
  time_updated: string;
}

export interface ConnectorSnapshot {
  id: number;
  name: string;
  source: ValidSources;
  input_type: ValidInputTypes;
  // connector_specific_config
  refresh_freq: number | null;
  prune_freq: number | null;
  credential_ids: number[];
  indexing_start: number | null;
  time_created: string;
  time_updated: string;
  from_beginning?: boolean;
}

export interface WebConfig {
  base_url: string;
  web_connector_type?: "recursive" | "single" | "sitemap";
}

export interface GithubConfig {
  repo_owner: string;
  repositories: string; // Comma-separated list of repository names
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
  include_shared_drives?: boolean;
  shared_drive_urls?: string;
  include_my_drives?: boolean;
  my_drive_emails?: string;
  shared_folder_urls?: string;
}

export interface GmailConfig {}

export interface BookstackConfig {}

export interface ConfluenceConfig {
  wiki_base: string;
  space?: string;
  page_id?: string;
  is_cloud?: boolean;
  index_recursively?: boolean;
  cql_query?: string;
}

export interface JiraConfig {
  jira_project_url: string;
  project_key?: string;
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
