import * as Yup from "yup";
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
  disabled?: boolean | ((currentCredential: Credential<any> | null) => boolean);
}

export interface SelectOption extends Option {
  type: "select";
  options?: StringWithDescription[];
  default?: string;
}

export interface MultiSelectOption extends Option {
  type: "multiselect";
  options?: StringWithDescription[];
  default?: string[];
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
      | MultiSelectOption
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
    | MultiSelectOption
    | FileOption
    | TabOption
  )[];
  advanced_values: (
    | BooleanOption
    | ListOption
    | TextOption
    | NumberOption
    | SelectOption
    | MultiSelectOption
    | FileOption
    | TabOption
  )[];
  overrideDefaultFreq?: number;
  advancedValuesVisibleCondition?: (
    values: any,
    currentCredential: Credential<any> | null
  ) => boolean;
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
    advanced_values: [
      {
        type: "checkbox",
        query: "Scroll before scraping:",
        label: "Scroll before scraping",
        description:
          "Enable if the website requires scrolling for the desired content to load",
        name: "scroll_before_scraping",
        optional: true,
      },
    ],
    overrideDefaultFreq: 60 * 60 * 24,
  },
  github: {
    description: "Configure GitHub connector",
    values: [
      {
        type: "text",
        query: "Enter the GitHub username or organization:",
        label: "Repository Owner",
        name: "repo_owner",
        optional: false,
      },
      {
        type: "tab",
        name: "github_mode",
        label: "What should we index from GitHub?",
        optional: true,
        tabs: [
          {
            value: "repo",
            label: "Specific Repository",
            fields: [
              {
                type: "text",
                query: "Enter the repository name(s):",
                label: "Repository Name(s)",
                name: "repositories",
                optional: false,
                description:
                  "For multiple repositories, enter comma-separated names (e.g., repo1,repo2,repo3)",
              },
            ],
          },
          {
            value: "everything",
            label: "Everything",
            fields: [
              {
                type: "string_tab",
                label: "Everything",
                name: "everything",
                description:
                  "This connector will index all repositories the provided credentials have access to!",
              },
            ],
          },
        ],
      },
      {
        type: "checkbox",
        query: "Include pull requests?",
        label: "Include pull requests?",
        description: "Index pull requests from repositories",
        name: "include_prs",
        optional: true,
      },
      {
        type: "checkbox",
        query: "Include issues?",
        label: "Include Issues?",
        name: "include_issues",
        description: "Index issues from repositories",
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
    ],
    advanced_values: [
      {
        type: "checkbox",
        query: "Include merge requests?",
        label: "Include MRs",
        name: "include_mrs",
        description: "Index merge requests from repositories",
        default: true,
      },
      {
        type: "checkbox",
        query: "Include issues?",
        label: "Include Issues",
        name: "include_issues",
        description: "Index issues from repositories",
        default: true,
      },
    ],
  },
  bitbucket: {
    description: "Configure Bitbucket connector",
    subtext:
      "Configure Bitbucket connector (Cloud only). You can index a workspace, specific projects or repositories.",
    values: [
      {
        type: "text",
        label: "Workspace",
        name: "workspace",
        optional: false,
        description: `The Bitbucket workspace to index (e.g., "atlassian" from https://bitbucket.org/atlassian/workspace ).`,
      },
      {
        type: "tab",
        name: "bitbucket_mode",
        label: "What should be indexed from Bitbucket?",
        optional: true,
        tabs: [
          {
            value: "repo",
            label: "Specific Repositories",
            fields: [
              {
                type: "text",
                label: "Repository Slugs",
                name: "repositories",
                optional: false,
                description:
                  "For multiple repositories, enter comma-separated slugs (e.g., repo1,repo2,repo3)",
              },
            ],
          },
          {
            value: "project",
            label: "Project(s)",
            fields: [
              {
                type: "text",
                label: "Project Key(s)",
                name: "projects",
                optional: false,
                description:
                  "One or more Bitbucket Project Keys (comma-separated) to index all repositories in those projects (e.g., PROJ1,PROJ2)",
              },
            ],
          },
          {
            value: "workspace",
            label: "Workspace",
            fields: [
              {
                type: "string_tab",
                label: "Workspace",
                name: "workspace_tab",
                description:
                  "This connector will index all repositories in the workspace.",
              },
            ],
          },
        ],
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
    advanced_values: [
      {
        type: "text",
        description:
          "Enter a comma separated list of specific user emails to index. This will only index files accessible to these users.",
        label: "Specific User Emails",
        name: "specific_user_emails",
        optional: true,
        default: "",
        isTextArea: true,
      },
    ],
    advancedValuesVisibleCondition: (values, currentCredential) =>
      !currentCredential?.credential_json?.google_tokens,
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
  outline: {
    description: "Configure Outline connector",
    values: [],
    advanced_values: [],
  },
  confluence: {
    description: "Configure Confluence connector",
    initialConnectorName: "cloud_name",
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
        disabled: (currentCredential) => {
          if (currentCredential?.credential_json?.confluence_refresh_token) {
            return true;
          }
          return false;
        },
      },
      {
        type: "text",
        query: "Enter the wiki base URL:",
        label: "Wiki Base URL",
        name: "wiki_base",
        optional: false,
        initial: (currentCredential) => {
          return currentCredential?.credential_json?.wiki_base ?? "";
        },
        disabled: (currentCredential) => {
          if (currentCredential?.credential_json?.confluence_refresh_token) {
            return true;
          }
          return false;
        },
        description:
          "The base URL of your Confluence instance (e.g., https://your-domain.atlassian.net/wiki)",
      },
      {
        type: "checkbox",
        query: "Using scoped token?",
        label: "Using scoped token",
        name: "scoped_token",
        optional: true,
        default: false,
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
                  "IMPORTANT: We currently only support CQL queries that return objects of type 'page'. This means all CQL queries must contain 'type=page' as the only type filter. It is also important that no filters for 'lastModified' are used as it will cause issues with our connector polling logic. We will still get all attachments and comments for the pages returned by the CQL query. Any 'lastmodified' filters will be overwritten. See Atlassian's [CQL documentation](https://developer.atlassian.com/server/confluence/advanced-searching-using-cql/) for more details.",
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
    subtext: `Configure which Jira content to index. You can index everything or specify a particular project.`,
    values: [
      {
        type: "text",
        query: "Enter the Jira base URL:",
        label: "Jira Base URL",
        name: "jira_base_url",
        optional: false,
        description:
          "The base URL of your Jira instance (e.g., https://your-domain.atlassian.net)",
      },
      {
        type: "checkbox",
        query: "Using scoped token?",
        label: "Using scoped token",
        name: "scoped_token",
        optional: true,
        default: false,
      },
      {
        type: "tab",
        name: "indexing_scope",
        label: "How Should We Index Your Jira?",
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
                  "This connector will index all issues the provided credentials have access to!",
              },
            ],
          },
          {
            value: "project",
            label: "Project",
            fields: [
              {
                type: "text",
                query: "Enter the project key:",
                label: "Project Key",
                name: "project_key",
                description:
                  "The key of a specific project to index (e.g., 'PROJ').",
              },
            ],
          },
          {
            value: "jql",
            label: "JQL Query",
            fields: [
              {
                type: "text",
                query: "Enter the JQL query:",
                label: "JQL Query",
                name: "jql_query",
                description:
                  "A custom JQL query to filter Jira issues." +
                  "\n\nIMPORTANT: Do not include any time-based filters in the JQL query as that will conflict with the connector's logic. Additionally, do not include ORDER BY clauses." +
                  "\n\nSee Atlassian's [JQL documentation](https://support.atlassian.com/jira-software-cloud/docs/advanced-search-reference-jql-fields/) for more details on syntax.",
              },
            ],
          },
        ],
        defaultTab: "everything",
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
        type: "tab",
        name: "salesforce_config_type",
        label: "Configuration Type",
        optional: true,
        tabs: [
          {
            value: "simple",
            label: "Simple",
            fields: [
              {
                type: "list",
                query: "Enter requested objects:",
                label: "Requested Objects",
                name: "requested_objects",
                optional: true,
                description:
                  "Specify the Salesforce object types you want us to index. If unsure, don't specify any objects and Onyx will default to indexing by 'Account'." +
                  "\n\nHint: Use the singular form of the object name (e.g., 'Opportunity' instead of 'Opportunities').",
              },
            ],
          },
          {
            value: "advanced",
            label: "Advanced",
            fields: [
              {
                type: "text",
                query: "Enter custom query config:",
                label: "Custom Query Config",
                name: "custom_query_config",
                optional: true,
                isTextArea: true,
                description:
                  "Enter a JSON configuration that precisely defines which fields and child objects to index. This gives you complete control over the data structure." +
                  "\n\nExample:" +
                  "\n{" +
                  '\n  "Account": {' +
                  '\n    "fields": ["Id", "Name", "Industry"],' +
                  '\n    "associations": {' +
                  '\n      "Contact": ["Id", "FirstName", "LastName", "Email"]' +
                  "\n    }" +
                  "\n  }" +
                  "\n}" +
                  "\n\n[See our docs](https://docs.onyx.app/admin/connectors/official/salesforce) for more details.",
              },
            ],
          },
        ],
        defaultTab: "simple",
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
• Specifying 'https://onyxai.sharepoint.com/sites/support' for example only indexes this site.
• Specifying 'https://onyxai.sharepoint.com/sites/support/subfolder' for example only indexes this folder.
`,
      },
    ],
    advanced_values: [
      {
        type: "checkbox",
        query: "Index Documents:",
        label: "Index Documents",
        name: "include_site_documents",
        optional: true,
        default: true,
        description:
          "Index documents of all SharePoint libraries or folders defined above.",
      },
      {
        type: "checkbox",
        query: "Index ASPX Sites:",
        label: "Index ASPX Sites",
        name: "include_site_pages",
        optional: true,
        default: true,
        description:
          "Index aspx-pages of all SharePoint sites defined above, even if a library or folder is specified.",
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
        label: "Files",
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
    values: [
      {
        type: "multiselect",
        query: "Select which HubSpot objects to index:",
        label: "Object Types",
        name: "object_types",
        options: [
          { name: "Tickets", value: "tickets" },
          { name: "Companies", value: "companies" },
          { name: "Deals", value: "deals" },
          { name: "Contacts", value: "contacts" },
        ],
        default: ["tickets", "companies", "deals", "contacts"],
        description:
          "Choose which HubSpot object types to index. All types are selected by default.",
        optional: false,
      },
    ],
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
    advanced_values: [
      {
        type: "number",
        label: "API Calls per Minute",
        name: "calls_per_minute",
        optional: true,
        description:
          "Restricts how many Zendesk API calls this connector can make per minute (applies only to this connector). See defaults: https://developer.zendesk.com/api-reference/introduction/rate-limits/",
      },
    ],
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
        type: "checkbox",
        label: "EU Data Residency",
        name: "european_residency",
        description:
          "Check this box if your bucket has EU data residency enabled.",
        optional: true,
        default: false,
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
  highspot: {
    description: "Configure Highspot connector",
    values: [
      {
        type: "tab",
        name: "highspot_scope",
        label: "What should we index from Highspot?",
        optional: true,
        tabs: [
          {
            value: "spots",
            label: "Specific Spots",
            fields: [
              {
                type: "list",
                query: "Enter the spot name(s):",
                label: "Spot Name(s)",
                name: "spot_names",
                optional: false,
                description: "For multiple spots, enter your spot one by one.",
              },
            ],
          },
          {
            value: "everything",
            label: "Everything",
            fields: [
              {
                type: "string_tab",
                label: "Everything",
                name: "everything",
                description:
                  "This connector will index all spots the provided credentials have access to!",
              },
            ],
          },
        ],
      },
    ],
    advanced_values: [],
  },
  imap: {
    description: "Configure Email connector",
    values: [
      {
        type: "text",
        query: "Enter the IMAP server host:",
        label: "IMAP Server Host",
        name: "host",
        optional: false,
        description:
          "The IMAP server hostname (e.g., imap.gmail.com, outlook.office365.com)",
      },
      {
        type: "number",
        query: "Enter the IMAP server port:",
        label: "IMAP Server Port",
        name: "port",
        optional: true,
        default: 993,
        description: "The IMAP server port (default: 993 for SSL)",
      },
      {
        type: "list",
        query: "Enter mailboxes to include:",
        label: "Mailboxes",
        name: "mailboxes",
        optional: true,
        description:
          "Specify mailboxes to index (e.g., INBOX, Sent, Drafts). Leave empty to index all mailboxes.",
      },
    ],
    advanced_values: [],
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
        } else if (field.type === "multiselect") {
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

  const object = Yup.object().shape({
    access_type: Yup.string().required("Access Type is required"),
    name: Yup.string().required("Connector Name is required"),
    ...[...configuration.values, ...configuration.advanced_values].reduce(
      (acc, field) => {
        let schema: any =
          field.type === "select"
            ? Yup.string()
            : field.type === "list"
              ? Yup.array().of(Yup.string())
              : field.type === "multiselect"
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
    pruneFreq: Yup.number().min(
      0.083,
      "Prune frequency must be at least 0.083 hours (5 minutes)"
    ),
    refreshFreq: Yup.number().min(
      1,
      "Refresh frequency must be at least 1 minute"
    ),
  });

  return object;
}

export const defaultPruneFreqHours = 720; // 30 days in hours
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
}

export interface JiraConfig {
  jira_project_url: string;
  project_key?: string;
  comment_email_blacklist?: string[];
  jql_query?: string;
}

export interface SalesforceConfig {
  requested_objects?: string[];
}

export interface SharepointConfig {
  sites?: string[];
  include_site_pages?: boolean;
  include_site_documents?: boolean;
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
  file_names: string[];
  zip_metadata: Record<string, any>;
}

export interface ZulipConfig {
  realm_name: string;
  realm_url: string;
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
