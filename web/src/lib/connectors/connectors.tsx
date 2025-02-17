import * as Yup from "yup";
import { IsPublicGroupSelectorFormType } from "@/components/IsPublicGroupSelector";
import { ConfigurableSources, ValidInputTypes, ValidSources } from "../types";
import { AccessTypeGroupSelectorFormType } from "@/components/admin/connectors/AccessTypeGroupSelector";
import { Credential } from "@/lib/connectors/credentials"; // Import Credential type

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
    description: "Configure Web connector",
    values: [
      {
        type: "text",
        query: "Enter the website URL to scrape e.g. https://docs.onyx.app/:",
        label: "Base URL",
        name: "base_url",
        optional: false,
      },
      {
        type: "select",
        query: "Select the web connector type:",
        label: "Scrape Method",
        name: "web_connector_type",
        options: [
          { name: "recursive", value: "recursive" },
          { name: "single", value: "single" },
          { name: "sitemap", value: "sitemap" },
        ],
      },
    ],
    advanced_values: [],
    overrideDefaultFreq: 60 * 60 * 24,
  },
  github: {
    description: "Configure GitHub connector",
    values: [
      {
        type: "text",
        query: "Enter the repository owner:",
        label: "Repository Owner",
        name: "repo_owner",
        optional: false,
      },
      {
        type: "text",
        query: "Enter the repository name:",
        label: "Repository Name",
        name: "repo_name",
        optional: false,
      },
      {
        type: "checkbox",
        query: "Include pull requests?",
        label: "Include pull requests?",
        description: "Index pull requests from this repository",
        name: "include_prs",
        optional: true,
      },
      {
        type: "checkbox",
        query: "Include issues?",
        label: "Include Issues",
        name: "include_issues",
        description: "Index issues from this repository",
        optional: true,
      },
    ],
    advanced_values: [],
  },
  gitlab: {
    description: "Configure GitLab connector",
    values: [
      {
        type: "text",
        query: "Enter the project owner:",
        label: "Project Owner",
        name: "project_owner",
        optional: false,
      },
      {
        type: "text",
        query: "Enter the project name:",
        label: "Project Name",
        name: "project_name",
        optional: false,
      },
      {
        type: "checkbox",
        query: "Include merge requests?",
        label: "Include MRs",
        name: "include_mrs",
        default: true,
        hidden: true,
      },
      {
        type: "checkbox",
        query: "Include issues?",
        label: "Include Issues",
        name: "include_issues",
        optional: true,
        hidden: true,
      },
    ],
    advanced_values: [],
  },
  gitbook: {
    description: "Configure GitBook connector",
    values: [
      {
        type: "text",
        query: "Enter the space ID:",
        label: "Space ID",
        name: "space_id",
        optional: false,
        description:
          "The ID of the GitBook space to index. This can be found in the URL " +
          "of a page in the space. For example, if your URL looks like " +
          "`https://app.gitbook.com/o/ccLx08XZ5wZ54LwdP9QU/s/8JkzVx8QCIGRrmxhGHU8/`, " +
          "then your space ID is `8JkzVx8QCIGRrmxhGHU8`.",
      },
    ],
    advanced_values: [],
  },
  google_drive: {
    description: "Configure Google Drive connector",
    values: [
      {
        type: "tab",
        name: "indexing_scope",
        label: "How should we index your Google Drive?",
        optional: true,
        tabs: [
          {
            value: "general",
            label: "General",
            fields: [
              {
                type: "checkbox",
                label: "Include shared drives?",
                description: (currentCredential) => {
                  return currentCredential?.credential_json?.google_tokens
                    ? "This will allow Onyx to index everything in the shared drives you have access to."
                    : "This will allow Onyx to index everything in your Organization's shared drives.";
                },
                name: "include_shared_drives",
                default: false,
              },
              {
                type: "checkbox",
                label: (currentCredential) => {
                  return currentCredential?.credential_json?.google_tokens
                    ? "Include My Drive?"
                    : "Include Everyone's My Drive?";
                },
                description: (currentCredential) => {
                  return currentCredential?.credential_json?.google_tokens
                    ? "This will allow Onyx to index everything in your My Drive."
                    : "This will allow Onyx to index everything in everyone's My Drives.";
                },
                name: "include_my_drives",
                default: false,
              },
              {
                type: "checkbox",
                description:
                  "This will allow Onyx to index all files shared with you.",
                label: "Include All Files Shared With You?",
                name: "include_files_shared_with_me",
                visibleCondition: (values, currentCredential) =>
                  currentCredential?.credential_json?.google_tokens,
                default: false,
              },
            ],
          },
          {
            value: "specific",
            label: "Specific",
            fields: [
              {
                type: "text",
                description: (currentCredential) => {
                  return currentCredential?.credential_json?.google_tokens
                    ? "Enter a comma separated list of the URLs for the shared drive you would like to index. You must have access to these shared drives."
                    : "Enter a comma separated list of the URLs for the shared drive you would like to index.";
                },
                label: "Shared Drive URLs",
                name: "shared_drive_urls",
                default: "",
                isTextArea: true,
              },
              {
                type: "text",
                description:
                  "Enter a comma separated list of the URLs of any folders you would like to index. The files located in these folders (and all subfolders) will be indexed.",
                label: "Folder URLs",
                name: "shared_folder_urls",
                default: "",
                isTextArea: true,
              },
              {
                type: "text",
                description:
                  "Enter a comma separated list of the emails of the users whose MyDrive you want to index.",
                label: "My Drive Emails",
                name: "my_drive_emails",
                visibleCondition: (values, currentCredential) =>
                  !currentCredential?.credential_json?.google_tokens,
                default: "",
                isTextArea: true,
              },
            ],
          },
        ],
        defaultTab: "space",
      },
    ],
    advanced_values: [],
  },
  gmail: {
    description: "Configure Gmail connector",
    values: [],
    advanced_values: [],
  },
  bookstack: {
    description: "Configure Bookstack connector",
    values: [],
    advanced_values: [],
  },
  confluence: {
    description: "Configure Confluence connector",
    values: [
      {
        type: "checkbox",
        query: "Is this a Confluence Cloud instance?",
        label: "Is Cloud",
        name: "is_cloud",
        optional: false,
        default: true,
        description:
          "Check if this is a Confluence Cloud instance, uncheck for Confluence Server/Data Center",
      },
      {
        type: "text",
        query: "Enter the wiki base URL:",
        label: "Wiki Base URL",
        name: "wiki_base",
        optional: false,
        description:
          "The base URL of your Confluence instance (e.g., https://your-domain.atlassian.net/wiki)",
      },
      {
        type: "tab",
        name: "indexing_scope",
        label: "How Should We Index Your Confluence?",
        optional: true,
        tabs: [
          {
            value: "everything",
            label: "Everything",
            fields: [
              {
                type: "string_tab",
                label: "Everything",
                name: "everything",
                description:
                  "This connector will index all pages the provided credentials have access to!",
              },
            ],
          },
          {
            value: "space",
            label: "Space",
            fields: [
              {
                type: "text",
                query: "Enter the space:",
                label: "Space Key",
                name: "space",
                default: "",
                description: "The Confluence space key to index (e.g. `KB`).",
              },
            ],
          },
          {
            value: "page",
            label: "Page",
            fields: [
              {
                type: "text",
                query: "Enter the page ID:",
                label: "Page ID",
                name: "page_id",
                default: "",
                description: "Specific page ID to index (e.g. `131368`)",
              },
              {
                type: "checkbox",
                query: "Should index pages recursively?",
                label: "Index Recursively",
                name: "index_recursively",
                description:
                  "If this is set, we will index the page indicated by the Page ID as well as all of its children.",
                optional: false,
                default: true,
              },
            ],
          },
          {
            value: "cql",
            label: "CQL Query",
            fields: [
              {
                type: "text",
                query: "Enter the CQL query (optional):",
                label: "CQL Query",
                name: "cql_query",
                default: "",
                description:
                  "IMPORTANT: We currently only support CQL queries that return objects of type 'page'. This means all CQL queries must contain 'type=page' as the only type filter. It is also important that no filters for 'lastModified' are used as it will cause issues with our connector polling logic. We will still get all attachments and comments for the pages returned by the CQL query. Any 'lastmodified' filters will be overwritten. See https://developer.atlassian.com/server/confluence/advanced-searching-using-cql/ for more details.",
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
    description: "Configure Jira connector",
    subtext: `Specify any link to a Jira page below and click "Index" to Index. Based on the provided link, we will index the ENTIRE PROJECT, not just the specified page. For example, entering https://onyx.atlassian.net/jira/software/projects/DAN/boards/1 and clicking the Index button will index the whole DAN Jira project.`,
    values: [
      {
        type: "text",
        query: "Enter the Jira project URL:",
        label: "Jira Project URL",
        name: "jira_project_url",
        optional: false,
      },
      {
        type: "list",
        query: "Enter email addresses to blacklist from comments:",
        label: "Comment Email Blacklist",
        name: "comment_email_blacklist",
        description:
          "This is generally useful to ignore certain bots. Add user emails which comments should NOT be indexed.",
        optional: true,
      },
    ],
    advanced_values: [],
  },
  salesforce: {
    description: "Configure Salesforce connector",
    values: [
      {
        type: "list",
        query: "Enter requested objects:",
        label: "Requested Objects",
        name: "requested_objects",
        optional: true,
        description: `Specify the Salesforce object types you want us to index. If unsure, don't specify any objects and Onyx will default to indexing by 'Account'.

Hint: Use the singular form of the object name (e.g., 'Opportunity' instead of 'Opportunities').`,
      },
    ],
    advanced_values: [],
  },
  sharepoint: {
    description: "Configure SharePoint connector",
    values: [
      {
        type: "list",
        query: "Enter SharePoint sites:",
        label: "Sites",
        name: "sites",
        optional: true,
        description: `• If no sites are specified, all sites in your organization will be indexed (Sites.Read.All permission required).

• Specifying 'https://onyxai.sharepoint.com/sites/support' for example will only index documents within this site.

• Specifying 'https://onyxai.sharepoint.com/sites/support/subfolder' for example will only index documents within this folder.
`,
      },
    ],
    advanced_values: [],
  },
  teams: {
    description: "Configure Teams connector",
    values: [
      {
        type: "list",
        query: "Enter Teams to include:",
        label: "Teams",
        name: "teams",
        optional: true,
        description: `Specify 0 or more Teams to index. For example, specifying the Team 'Support' for the 'onyxai' Org will cause us to only index messages sent in channels belonging to the 'Support' Team. If no Teams are specified, all Teams in your organization will be indexed.`,
      },
    ],
    advanced_values: [],
  },
  discourse: {
    description: "Configure Discourse connector",
    values: [
      {
        type: "text",
        query: "Enter the base URL:",
        label: "Base URL",
        name: "base_url",
        optional: false,
      },
      {
        type: "list",
        query: "Enter categories to include:",
        label: "Categories",
        name: "categories",
        optional: true,
      },
    ],
    advanced_values: [],
  },
  axero: {
    description: "Configure Axero connector",
    values: [
      {
        type: "list",
        query: "Enter spaces to include:",
        label: "Spaces",
        name: "spaces",
        optional: true,
        description:
          "Specify zero or more Spaces to index (by the Space IDs). If no Space IDs are specified, all Spaces will be indexed.",
      },
    ],
    advanced_values: [],
    overrideDefaultFreq: 60 * 60 * 24,
  },
  productboard: {
    description: "Configure Productboard connector",
    values: [],
    advanced_values: [],
  },
  slack: {
    description: "Configure Slack connector",
    values: [],
    advanced_values: [
      {
        type: "list",
        query: "Enter channels to include:",
        label: "Channels",
        name: "channels",
        description: `Specify 0 or more channels to index. For example, specifying the channel "support" will cause us to only index all content within the "#support" channel. If no channels are specified, all channels in your workspace will be indexed.`,
        optional: true,
        // Slack Channels can only be lowercase
        transform: (values) => values.map((value) => value.toLowerCase()),
      },
      {
        type: "checkbox",
        query: "Enable channel regex?",
        label: "Enable Channel Regex",
        name: "channel_regex_enabled",
        description: `If enabled, we will treat the "channels" specified above as regular expressions. A channel's messages will be pulled in by the connector if the name of the channel fully matches any of the specified regular expressions.
For example, specifying .*-support.* as a "channel" will cause the connector to include any channels with "-support" in the name.`,
        optional: true,
      },
    ],
  },
  slab: {
    description: "Configure Slab connector",
    values: [
      {
        type: "text",
        query: "Enter the base URL:",
        label: "Base URL",
        name: "base_url",
        optional: false,
        description: `Specify the base URL for your Slab team. This will look something like: https://onyx.slab.com/`,
      },
    ],
    advanced_values: [],
  },
  guru: {
    description: "Configure Guru connector",
    values: [],
    advanced_values: [],
  },
  gong: {
    description: "Configure Gong connector",
    values: [
      {
        type: "list",
        query: "Enter workspaces to include:",
        label: "Workspaces",
        name: "workspaces",
        optional: true,
        description:
          "Specify 0 or more workspaces to index. Provide the workspace ID or the EXACT workspace name from Gong. If no workspaces are specified, transcripts from all workspaces will be indexed.",
      },
    ],
    advanced_values: [],
  },
  loopio: {
    description: "Configure Loopio connector",
    values: [
      {
        type: "text",
        query: "Enter the Loopio stack name",
        label: "Loopio Stack Name",
        name: "loopio_stack_name",
        description:
          "Must be exact match to the name in Library Management, leave this blank if you want to index all Stacks",
        optional: true,
      },
    ],
    advanced_values: [],
    overrideDefaultFreq: 60 * 60 * 24,
  },
  file: {
    description: "Configure File connector",
    values: [
      {
        type: "file",
        query: "Enter file locations:",
        label: "File Locations",
        name: "file_locations",
        optional: false,
      },
    ],
    advanced_values: [],
  },
  zulip: {
    description: "Configure Zulip connector",
    values: [
      {
        type: "text",
        query: "Enter the realm name",
        label: "Realm Name",
        name: "realm_name",
        optional: false,
      },
      {
        type: "text",
        query: "Enter the realm URL",
        label: "Realm URL",
        name: "realm_url",
        optional: false,
      },
    ],
    advanced_values: [],
  },
  notion: {
    description: "Configure Notion connector",
    values: [
      {
        type: "text",
        query: "Enter the root page ID",
        label: "Root Page ID",
        name: "root_page_id",
        optional: true,
        description:
          "If specified, will only index the specified page + all of its child pages. If left blank, will index all pages the integration has been given access to.",
      },
    ],
    advanced_values: [],
  },
  hubspot: {
    description: "Configure HubSpot connector",
    values: [],
    advanced_values: [],
  },
  document360: {
    description: "Configure Document360 connector",
    values: [
      {
        type: "text",
        query: "Enter the workspace",
        label: "Workspace",
        name: "workspace",
        optional: false,
      },
      {
        type: "list",
        query: "Enter categories to include",
        label: "Categories",
        name: "categories",
        optional: true,
        description:
          "Specify 0 or more categories to index. For instance, specifying the category 'Help' will cause us to only index all content within the 'Help' category. If no categories are specified, all categories in your workspace will be indexed.",
      },
    ],
    advanced_values: [],
  },
  clickup: {
    description: "Configure ClickUp connector",
    values: [
      {
        type: "select",
        query: "Select the connector type:",
        label: "Connector Type",
        name: "connector_type",
        optional: false,
        options: [
          { name: "list", value: "list" },
          { name: "folder", value: "folder" },
          { name: "space", value: "space" },
          { name: "workspace", value: "workspace" },
        ],
      },
      {
        type: "list",
        query: "Enter connector IDs:",
        label: "Connector IDs",
        name: "connector_ids",
        description: "Specify 0 or more id(s) to index from.",
        optional: true,
      },
      {
        type: "checkbox",
        query: "Retrieve task comments?",
        label: "Retrieve Task Comments",
        name: "retrieve_task_comments",
        description:
          "If checked, then all the comments for each task will also be retrieved and indexed.",
        optional: false,
      },
    ],
    advanced_values: [],
  },
  google_sites: {
    description: "Configure Google Sites connector",
    values: [
      {
        type: "file",
        query: "Enter the zip path:",
        label: "File Locations",
        name: "file_locations",
        optional: false,
        description:
          "Upload a zip file containing the HTML of your Google Site",
      },
      {
        type: "text",
        query: "Enter the base URL:",
        label: "Base URL",
        name: "base_url",
        optional: false,
      },
    ],
    advanced_values: [],
  },
  zendesk: {
    description: "Configure Zendesk connector",
    values: [
      {
        type: "select",
        query: "Select the what content this connector will index:",
        label: "Content Type",
        name: "content_type",
        optional: false,
        options: [
          { name: "articles", value: "articles" },
          { name: "tickets", value: "tickets" },
        ],
        default: "articles",
      },
    ],
    advanced_values: [],
  },
  linear: {
    description: "Configure Linear connector",
    values: [],
    advanced_values: [],
  },
  dropbox: {
    description: "Configure Dropbox connector",
    values: [],
    advanced_values: [],
  },
  s3: {
    description: "Configure S3 connector",
    values: [
      {
        type: "text",
        query: "Enter the bucket name:",
        label: "Bucket Name",
        name: "bucket_name",
        optional: false,
      },
      {
        type: "text",
        query: "Enter the prefix:",
        label: "Prefix",
        name: "prefix",
        optional: true,
      },
      {
        type: "text",
        label: "Bucket Type",
        name: "bucket_type",
        optional: false,
        default: "s3",
        hidden: true,
      },
    ],
    advanced_values: [],
    overrideDefaultFreq: 60 * 60 * 24,
  },
  r2: {
    description: "Configure R2 connector",
    values: [
      {
        type: "text",
        query: "Enter the bucket name:",
        label: "Bucket Name",
        name: "bucket_name",
        optional: false,
      },
      {
        type: "text",
        query: "Enter the prefix:",
        label: "Prefix",
        name: "prefix",
        optional: true,
      },
      {
        type: "text",
        label: "Bucket Type",
        name: "bucket_type",
        optional: false,
        default: "r2",
        hidden: true,
      },
    ],
    advanced_values: [],
    overrideDefaultFreq: 60 * 60 * 24,
  },
  google_cloud_storage: {
    description: "Configure Google Cloud Storage connector",
    values: [
      {
        type: "text",
        query: "Enter the bucket name:",
        label: "Bucket Name",
        name: "bucket_name",
        optional: false,
        description: "Name of the GCS bucket to index, e.g. my-gcs-bucket",
      },
      {
        type: "text",
        query: "Enter the prefix:",
        label: "Path Prefix",
        name: "prefix",
        optional: true,
      },
      {
        type: "text",
        label: "Bucket Type",
        name: "bucket_type",
        optional: false,
        default: "google_cloud_storage",
        hidden: true,
      },
    ],
    advanced_values: [],
    overrideDefaultFreq: 60 * 60 * 24,
  },
  oci_storage: {
    description: "Configure OCI Storage connector",
    values: [
      {
        type: "text",
        query: "Enter the bucket name:",
        label: "Bucket Name",
        name: "bucket_name",
        optional: false,
      },
      {
        type: "text",
        query: "Enter the prefix:",
        label: "Prefix",
        name: "prefix",
        optional: true,
      },
      {
        type: "text",
        label: "Bucket Type",
        name: "bucket_type",
        optional: false,
        default: "oci_storage",
        hidden: true,
      },
    ],
    advanced_values: [],
  },
  wikipedia: {
    description: "Configure Wikipedia connector",
    values: [
      {
        type: "text",
        query: "Enter the language code:",
        label: "Language Code",
        name: "language_code",
        optional: false,
        description: "Input a valid Wikipedia language code (e.g. 'en', 'es')",
      },
      {
        type: "list",
        query: "Enter categories to include:",
        label: "Categories to index",
        name: "categories",
        description:
          "Specify 0 or more names of categories to index. For most Wikipedia sites, these are pages with a name of the form 'Category: XYZ', that are lists of other pages/categories. Only specify the name of the category, not its url.",
        optional: true,
      },
      {
        type: "list",
        query: "Enter pages to include:",
        label: "Pages",
        name: "pages",
        optional: true,
        description: "Specify 0 or more names of pages to index.",
      },
      {
        type: "number",
        query: "Enter the recursion depth:",
        label: "Recursion Depth",
        name: "recurse_depth",
        description:
          "When indexing categories that have sub-categories, this will determine how may levels to index. Specify 0 to only index the category itself (i.e. no recursion). Specify -1 for unlimited recursion depth. Note, that in some rare instances, a category might contain itself in its dependencies, which will cause an infinite loop. Only use -1 if you confident that this will not happen.",
        optional: false,
      },
    ],
    advanced_values: [],
  },
  xenforo: {
    description: "Configure Xenforo connector",
    values: [
      {
        type: "text",
        query: "Enter forum or thread URL:",
        label: "URL",
        name: "base_url",
        optional: false,
        description:
          "The XenForo v2.2 forum URL to index. Can be board or thread.",
      },
    ],
    advanced_values: [],
  },
  asana: {
    description: "Configure Asana connector",
    values: [
      {
        type: "text",
        query: "Enter your Asana workspace ID:",
        label: "Workspace ID",
        name: "asana_workspace_id",
        optional: false,
        description:
          "The ID of the Asana workspace to index. You can find this at https://app.asana.com/api/1.0/workspaces. It's a number that looks like 1234567890123456.",
      },
      {
        type: "text",
        query: "Enter project IDs to index (optional):",
        label: "Project IDs",
        name: "asana_project_ids",
        description:
          "IDs of specific Asana projects to index, separated by commas. Leave empty to index all projects in the workspace. Example: 1234567890123456,2345678901234567",
        optional: true,
      },
      {
        type: "text",
        query: "Enter the Team ID (optional):",
        label: "Team ID",
        name: "asana_team_id",
        optional: true,
        description:
          "ID of a team to use for accessing team-visible tasks. This allows indexing of team-visible tasks in addition to public tasks. Leave empty if you don't want to use this feature.",
      },
    ],
    advanced_values: [],
  },
  mediawiki: {
    description: "Configure MediaWiki connector",
    values: [
      {
        type: "text",
        query: "Enter the language code:",
        label: "Language Code",
        name: "language_code",
        optional: false,
        description: "Input a valid MediaWiki language code (e.g. 'en', 'es')",
      },
      {
        type: "text",
        query: "Enter the MediaWiki Site URL",
        label: "MediaWiki Site URL",
        name: "hostname",
        optional: false,
      },
      {
        type: "list",
        query: "Enter categories to include:",
        label: "Categories to index",
        name: "categories",
        description:
          "Specify 0 or more names of categories to index. For most MediaWiki sites, these are pages with a name of the form 'Category: XYZ', that are lists of other pages/categories. Only specify the name of the category, not its url.",
        optional: true,
      },
      {
        type: "list",
        query: "Enter pages to include:",
        label: "Pages",
        name: "pages",
        optional: true,
        description:
          "Specify 0 or more names of pages to index. Only specify the name of the page, not its url.",
      },
      {
        type: "number",
        query: "Enter the recursion depth:",
        label: "Recursion Depth",
        name: "recurse_depth",
        description:
          "When indexing categories that have sub-categories, this will determine how may levels to index. Specify 0 to only index the category itself (i.e. no recursion). Specify -1 for unlimited recursion depth. Note, that in some rare instances, a category might contain itself in its dependencies, which will cause an infinite loop. Only use -1 if you confident that this will not happen.",
        optional: true,
      },
    ],
    advanced_values: [],
  },
  discord: {
    description: "Configure Discord connector",
    values: [],
    advanced_values: [
      {
        type: "list",
        query: "Enter Server IDs to include:",
        label: "Server IDs",
        name: "server_ids",
        description: `Specify 0 or more server ids to include. Only channels inside them will be used for indexing`,
        optional: true,
      },
      {
        type: "list",
        query: "Enter channel names to include:",
        label: "Channels",
        name: "channel_names",
        description: `Specify 0 or more channels to index. For example, specifying the channel "support" will cause us to only index all content within the "#support" channel. If no channels are specified, all channels the bot has access to will be indexed.`,
        optional: true,
      },
      {
        type: "text",
        query: "Enter the Start Date:",
        label: "Start Date",
        name: "start_date",
        description: `Only messages after this date will be indexed. Format: YYYY-MM-DD`,
        optional: true,
      },
    ],
  },
  freshdesk: {
    description: "Configure Freshdesk connector",
    values: [],
    advanced_values: [],
  },
  fireflies: {
    description: "Configure Fireflies connector",
    values: [],
    advanced_values: [],
  },
  egnyte: {
    description: "Configure Egnyte connector",
    values: [
      {
        type: "text",
        query: "Enter folder path to index:",
        label: "Folder Path",
        name: "folder_path",
        optional: true,
        description:
          "The folder path to index (e.g., '/Shared/Documents'). Leave empty to index everything.",
      },
    ],
    advanced_values: [],
  },
  airtable: {
    description: "Configure Airtable connector",
    values: [
      {
        type: "text",
        query: "Enter the base ID:",
        label: "Base ID",
        name: "base_id",
        optional: false,
        description: "The ID of the Airtable base to index.",
      },
      {
        type: "text",
        query: "Enter the table name or ID:",
        label: "Table Name or Table ID",
        name: "table_name_or_id",
        optional: false,
      },
      {
        type: "checkbox",
        label: "Treat all fields except attachments as metadata",
        name: "treat_all_non_attachment_fields_as_metadata",
        description:
          "Choose this if the primary content to index are attachments and all other columns are metadata for these attachments.",
        optional: false,
      },
    ],
    advanced_values: [
      {
        type: "text",
        label: "View ID",
        name: "view_id",
        optional: true,
        description:
          "If you need to link to a specific View, put that ID here e.g. viwVUEJjWPd8XYjh8.",
      },
      {
        type: "text",
        label: "Share ID",
        name: "share_id",
        optional: true,
        description:
          "If you need to link to a specific Share, put that ID here e.g. shrkfjEzDmLaDtK83.",
      },
    ],
    overrideDefaultFreq: 60 * 60 * 24,
  },
};
export function createConnectorInitialValues(
  connector: ConfigurableSources
): Record<string, any> & AccessTypeGroupSelectorFormType {
  const configuration = connectorConfigs[connector];

  return {
    name: "",
    groups: [],
    access_type: "public",
    ...configuration.values.reduce(
      (acc, field) => {
        if (field.type === "select") {
          acc[field.name] = null;
        } else if (field.type === "list") {
          acc[field.name] = field.default || [];
        } else if (field.type === "checkbox") {
          acc[field.name] = field.default || false;
        } else if (field.default !== undefined) {
          acc[field.name] = field.default;
        }
        return acc;
      },
      {} as { [record: string]: any }
    ),
  };
}

export function createConnectorValidationSchema(
  connector: ConfigurableSources
): Yup.ObjectSchema<Record<string, any>> {
  const configuration = connectorConfigs[connector];

  return Yup.object().shape({
    access_type: Yup.string().required("Access Type is required"),
    name: Yup.string().required("Connector Name is required"),
    ...configuration.values.reduce(
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
          schema = schema.required(`${field.label} is required`);
        }

        acc[field.name] = schema;
        return acc;
      },
      {} as Record<string, any>
    ),
    // These are advanced settings
    indexingStart: Yup.string().nullable(),
    pruneFreq: Yup.number().min(0, "Prune frequency must be non-negative"),
    refreshFreq: Yup.number().min(0, "Refresh frequency must be non-negative"),
  });
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
