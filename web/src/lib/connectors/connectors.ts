import { ValidInputTypes, ValidSources } from "../types";

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
  label: string;
  name: string;
  description?: string;
  query?: string;
  optional?: boolean;
  hidden?: boolean;
}

export interface SelectOption extends Option {
  type: "select";
  default?: number;
  options?: StringWithDescription[];
}

export interface ListOption extends Option {
  type: "list";
  default?: string[];
}

export interface TextOption extends Option {
  type: "text";
  default?: string;
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

export interface ZipOption extends Option {
  type: "zip";
  default?: string;
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
    | ZipOption
  )[];
  overrideDefaultFreq?: number;
}

export const connectorConfigs: Record<ValidSources, ConnectionConfiguration> = {
  web: {
    description: "Configure Web connector",
    values: [
      {
        type: "text",
        query:
          "Enter the website URL to scrape e.g. https://docs.danswer.dev/:",
        label: "Base URL",
        name: "base_url",
        optional: false,
      },
      {
        type: "select",
        query: "Select the web connector type:",
        label: "Scrape Method",
        name: "web_connector_type",
        optional: true,
        options: [
          { name: "recursive", value: "recursive" },
          { name: "single", value: "single" },
          { name: "sitemap", value: "sitemap" },
        ],
      },
    ],
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
  },
  google_drive: {
    description: "Configure Google Drive connector",
    values: [
      {
        type: "list",
        query: "Enter folder paths:",
        label: "Folder Paths",
        name: "folder_paths",
        optional: true,
      },
      {
        type: "checkbox",
        query: "Include shared files?",
        label: "Include Shared",
        name: "include_shared",
        optional: false,
        default: false,
      },
      {
        type: "checkbox",
        query: "Follow shortcuts?",
        label: "Follow Shortcuts",
        name: "follow_shortcuts",
        optional: false,
        default: false,
      },
      {
        type: "checkbox",
        query: "Only include organization public files?",
        label: "Only Org Public",
        name: "only_org_public",
        optional: false,
        default: false,
      },
    ],
  },
  gmail: {
    description: "Configure Gmail connector",
    values: [],
  },
  bookstack: {
    description: "Configure Bookstack connector",
    values: [],
  },
  confluence: {
    description: "Configure Confluence connector",
    subtext: `Specify any link to a Confluence page below and click "Index" to Index. If the provided link is for an entire space, we will index the entire space. However, if you want to index a specific page, you can do so by entering the page's URL. 
    
For example, entering https://danswer.atlassian.net/wiki/spaces/Engineering/overview and clicking the Index button will index the whole Engineering Confluence space, but entering https://danswer.atlassian.net/wiki/spaces/Engineering/pages/164331/example+page will index that page (and optionally the page's children). 

Selecting the "Index Recursively" checkbox will index the single page's children in addition to itself.

We pull the latest pages and comments from each space every 10 minutes`,
    values: [
      {
        type: "text",
        query: "Enter the wiki page URL:",
        label: "Wiki Page URL",
        name: "wiki_page_url",
        optional: false,
        description: "Enter any link to a Confluence space or Page",
      },
      {
        type: "checkbox",
        query: "Should index pages recursively?",
        label:
          "Index Recursively (if this is set and the Wiki Page URL leads to a page, we will index the page and all of its children instead of just the page)",
        name: "index_recursively",
        optional: false,
      },
    ],
  },
  jira: {
    description: "Configure Jira connector",
    subtext: `Specify any link to a Jira page below and click "Index" to Index. Based on the provided link, we will index the ENTIRE PROJECT, not just the specified page. For example, entering https://danswer.atlassian.net/jira/software/projects/DAN/boards/1 and clicking the Index button will index the whole DAN Jira project.`,
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
        description: `Specify the Salesforce object types you want us to index. If unsure, don't specify any objects and Danswer will default to indexing by 'Account'.

Hint: Use the singular form of the object name (e.g., 'Opportunity' instead of 'Opportunities').`,
      },
    ],
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
• Specifying 'https://danswerai.sharepoint.com/sites/support' for example will only index documents within this site.
• Specifying 'https://danswerai.sharepoint.com/sites/support/subfolder' for example will only index documents within this folder.
`,
      },
    ],
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
        description: `Specify 0 or more Teams to index. For example, specifying the Team 'Support' for the 'danswerai' Org will cause us to only index messages sent in channels belonging to the 'Support' Team. If no Teams are specified, all Teams in your organization will be indexed.`,
      },
    ],
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
    overrideDefaultFreq: 60 * 60 * 24,
  },
  productboard: {
    description: "Configure Productboard connector",
    values: [],
  },
  slack: {
    description: "Configure Slack connector",
    values: [
      {
        type: "text",
        query: "Enter the Slack workspace:",
        label: "Workspace",
        name: "workspace",
        optional: false,
      },
      {
        type: "list",
        query: "Enter channels to include:",
        label: "Channels",
        name: "channels",
        description: `Specify 0 or more channels to index. For example, specifying the channel "support" will cause us to only index all content within the "#support" channel. If no channels are specified, all channels in your workspace will be indexed.`,
        optional: true,
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
        description: `Specify the base URL for your Slab team. This will look something like: https://danswer.slab.com/`,
      },
    ],
  },
  guru: {
    description: "Configure Guru connector",
    values: [],
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
  },
  requesttracker: {
    description: "Configure HubSpot connector",
    values: [],
  },
  hubspot: {
    description: "Configure HubSpot connector",
    values: [],
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
  },
  google_sites: {
    description: "Configure Google Sites connector",
    values: [
      {
        type: "zip",
        query: "Enter the zip path:",
        label: "Zip Path",
        name: "zip_path",
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
  },
  zendesk: {
    description: "Configure Zendesk connector",
    values: [],
  },
  linear: {
    description: "Configure Dropbox connector",
    values: [],
  },
  dropbox: {
    description: "Configure Dropbox connector",
    values: [],
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
  },
};

// CONNECTORS
export interface ConnectorBase<T> {
  name: string;
  source: ValidSources;
  input_type: ValidInputTypes;
  connector_specific_config: T;
  refresh_freq: number | null;
  prune_freq: number | null;
  indexing_start: Date | null;
  is_public?: boolean;
  groups?: number[];
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
  index_recursively?: boolean;
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
