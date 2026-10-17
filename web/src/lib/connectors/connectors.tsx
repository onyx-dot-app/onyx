import type { ConfigurableSources } from "@/lib/connectors/types/source";
import { DOCS_ADMINS_PATH } from "@/lib/constants";
import { useMemo } from "react";
import { useTranslations } from "next-intl";
import type {
  BooleanOption,
  ConnectionConfiguration,
  ListOption,
} from "@/lib/connectors/types";
import { OneDriveScope } from "@/lib/connectors/types";
import { googleCredentialKind } from "@/lib/credentials/utils";
import type { CredentialValues } from "@/lib/credentials/types";

const DEFAULT_MICROSOFT_AUTHORITY_HOST = "https://login.microsoftonline.com";
const DEFAULT_MICROSOFT_GRAPH_API_HOST = "https://graph.microsoft.com";

interface OneDriveConfigurationText {
  description: string;
  indexingScopeLabel: string;
  generalLabel: string;
  generalDescription: string;
  specificLabel: string;
  usersLabel: string;
  usersDescription: string;
  excludedPathsLabel: string;
  excludedPathsDescription: string;
  organizationLinksLabel: string;
  organizationLinksDescription: string;
  authorityHostLabel: string;
  authorityHostDescription: string;
  graphApiHostLabel: string;
  graphApiHostDescription: string;
}

const ONE_DRIVE_TRANSLATION_KEYS: OneDriveConfigurationText = {
  description: "oneDrive.description",
  indexingScopeLabel: "oneDrive.indexingScope.label",
  generalLabel: "oneDrive.indexingScope.general.label",
  generalDescription: "oneDrive.indexingScope.general.description",
  specificLabel: "oneDrive.indexingScope.specific.label",
  usersLabel: "oneDrive.indexingScope.specific.users.label",
  usersDescription: "oneDrive.indexingScope.specific.users.description",
  excludedPathsLabel: "oneDrive.excludedPaths.label",
  excludedPathsDescription: "oneDrive.excludedPaths.description",
  organizationLinksLabel: "oneDrive.organizationLinks.label",
  organizationLinksDescription: "oneDrive.organizationLinks.description",
  authorityHostLabel: "oneDrive.authorityHost.label",
  authorityHostDescription: "oneDrive.authorityHost.description",
  graphApiHostLabel: "oneDrive.graphApiHost.label",
  graphApiHostDescription: "oneDrive.graphApiHost.description",
};

function buildOneDriveConfiguration(
  text: OneDriveConfigurationText
): ConnectionConfiguration {
  return {
    description: text.description,
    values: [
      {
        type: "tab",
        name: "indexing_scope",
        label: text.indexingScopeLabel,
        optional: true,
        tabs: [
          {
            value: OneDriveScope.General,
            label: text.generalLabel,
            fields: [
              {
                type: "string_tab",
                label: text.generalLabel,
                name: "all_users_description",
                optional: true,
                description: text.generalDescription,
              },
            ],
          },
          {
            value: OneDriveScope.Specific,
            label: text.specificLabel,
            fields: [
              {
                type: "list",
                label: text.usersLabel,
                name: "users",
                optional: true,
                default: [],
                description: text.usersDescription,
              },
            ],
          },
        ],
        defaultTab: OneDriveScope.General,
      },
    ],
    advanced_values: [
      {
        type: "list",
        label: text.excludedPathsLabel,
        name: "excluded_paths",
        optional: true,
        default: [],
        description: text.excludedPathsDescription,
      },
      {
        type: "checkbox",
        label: text.organizationLinksLabel,
        name: "treat_organization_link_as_public",
        optional: true,
        default: false,
        description: text.organizationLinksDescription,
      },
      {
        type: "text",
        label: text.authorityHostLabel,
        name: "authority_host",
        optional: true,
        default: DEFAULT_MICROSOFT_AUTHORITY_HOST,
        description: text.authorityHostDescription,
      },
      {
        type: "text",
        label: text.graphApiHostLabel,
        name: "graph_api_host",
        optional: true,
        default: DEFAULT_MICROSOFT_GRAPH_API_HOST,
        description: text.graphApiHostDescription,
      },
    ],
  };
}

interface LinearConfigurationText {
  description: string;
  teamsLabel: string;
  teamsDescription: string;
  projectsLabel: string;
  projectsDescription: string;
}

const LINEAR_TRANSLATION_KEYS: LinearConfigurationText = {
  description: "linear.description",
  teamsLabel: "linear.teams.label",
  teamsDescription: "linear.teams.description",
  projectsLabel: "linear.projects.label",
  projectsDescription: "linear.projects.description",
};

function buildLinearConfiguration(
  text: LinearConfigurationText
): ConnectionConfiguration {
  return {
    description: text.description,
    values: [
      {
        type: "list",
        label: text.teamsLabel,
        name: "team_keys",
        description: text.teamsDescription,
        optional: true,
      },
      {
        type: "list",
        label: text.projectsLabel,
        name: "projects",
        description: text.projectsDescription,
        optional: true,
      },
    ],
    advanced_values: [],
  };
}

type ConnectorField = ConnectionConfiguration["values"][number];
type FieldText =
  | string
  | ((currentCredential: CredentialValues | null) => string);

/**
 * The connector's form config with its copy translated: labels,
 * descriptions, placeholders, and tab and option names. The configs hold
 * message keys under `admin.connectorsList` (`connectors.<source>...`, and
 * OneDrive's and Linear's own namespaces); this swaps in the messages.
 */
export function useConnectorConfiguration(
  connector: ConfigurableSources
): ConnectionConfiguration {
  const t = useTranslations("admin.connectorsList");
  return useMemo(
    () =>
      translateConfiguration(connectorConfigs[connector], (key) =>
        // SAFETY: every copy string in `connectorConfigs` is a key of
        // `admin.connectorsList`; `connectorCopy.test.ts` checks each one
        // against en.json.
        t(key as Parameters<typeof t>[0], {
          docsAdminsPath: DOCS_ADMINS_PATH,
        })
      ),
    [connector, t]
  );
}

export function translateConfiguration(
  config: ConnectionConfiguration,
  translate: (key: string) => string
): ConnectionConfiguration {
  const text = (value: FieldText): FieldText =>
    typeof value === "function"
      ? (currentCredential) => translate(value(currentCredential))
      : translate(value);
  const field = <T extends ConnectorField>(f: T): T => {
    const out: ConnectorField = {
      ...f,
      ...(f.label !== undefined && { label: text(f.label) }),
      ...(f.description !== undefined && {
        description: text(f.description),
      }),
    };
    if (out.type === "tab") {
      out.tabs = out.tabs.map((tab) => ({
        ...tab,
        label: translate(tab.label),
        fields: tab.fields.map(field),
      }));
    }
    if ((out.type === "select" || out.type === "multiselect") && out.options) {
      out.options = out.options.map((option) => ({
        ...option,
        name: translate(option.name),
      }));
    }
    if (out.type === "text" && out.placeholder !== undefined) {
      out.placeholder = translate(out.placeholder);
    }
    if (out.type === "string_pair_list") {
      out.leftLabel = translate(out.leftLabel);
      out.rightLabel = translate(out.rightLabel);
      if (out.leftPlaceholder !== undefined) {
        out.leftPlaceholder = translate(out.leftPlaceholder);
      }
      if (out.rightPlaceholder !== undefined) {
        out.rightPlaceholder = translate(out.rightPlaceholder);
      }
    }
    // SAFETY: `out` is a copy of `f` with only its copy replaced.
    return out as T;
  };
  return {
    ...config,
    description: translate(config.description),
    ...(config.subtext !== undefined && {
      subtext: translate(config.subtext),
    }),
    values: config.values.map(field),
    advanced_values: config.advanced_values.map(field),
  };
}

// Shared "Include Attachments" checkbox. Pair with an `include_attachments`
// kwarg on the backend connector; see backend/onyx/connectors/README.md for
// the convention, including how to pick the default.
export function buildIncludeAttachmentsOption(
  defaultValue: boolean,
  description: string = "connectors.shared.fields.include_attachments.description"
): BooleanOption {
  return {
    type: "checkbox",
    label: "connectors.shared.fields.include_attachments.label",
    name: "include_attachments",
    description,
    default: defaultValue,
  };
}

const zoomMeetingIdsOption: ListOption = {
  type: "list",
  label: "connectors.zoom.fields.meeting_ids.label",
  name: "meeting_ids",
  optional: true,
  description: "connectors.zoom.fields.meeting_ids.description",
};

const zoomWebinarIdsOption: ListOption = {
  type: "list",
  label: "connectors.zoom.fields.webinar_ids.label",
  name: "webinar_ids",
  optional: true,
  description: "connectors.zoom.fields.webinar_ids.description",
};

/**
 * Whether an Atlassian API token (Confluence, Jira) has scopes. It sits below
 * the site URL in both connectors.
 */
const ATLASSIAN_SCOPED_TOKEN_FIELD: BooleanOption = {
  type: "checkbox",
  label: "connectors.shared.fields.scoped_token.label",
  description: "connectors.shared.fields.scoped_token.description",
  name: "scoped_token",
  optional: true,
  default: false,
  asCheckbox: true,
};

export const connectorConfigs: Record<
  ConfigurableSources,
  ConnectionConfiguration
> = {
  web: {
    description: "connectors.web.description",
    values: [
      {
        type: "text",
        label: "connectors.web.fields.base_url.label",
        name: "base_url",
        placeholder: "connectors.web.fields.base_url.placeholder",
        optional: false,
      },
      {
        type: "select",
        label: "connectors.web.fields.web_connector_type.label",
        name: "web_connector_type",
        options: [
          {
            name: "connectors.web.fields.web_connector_type.options.recursive",
            value: "recursive",
          },
          {
            name: "connectors.web.fields.web_connector_type.options.single",
            value: "single",
          },
          {
            name: "connectors.web.fields.web_connector_type.options.sitemap",
            value: "sitemap",
          },
        ],
      },
    ],
    advanced_values: [
      {
        type: "checkbox",
        label: "connectors.web.fields.scroll_before_scraping.label",
        description: "connectors.web.fields.scroll_before_scraping.description",
        name: "scroll_before_scraping",
        optional: true,
      },
      {
        type: "string_pair_list",
        label: "connectors.web.fields.url_rewrites.label",
        name: "url_rewrites",
        leftKey: "source",
        rightKey: "target",
        optional: true,
        description: "connectors.web.fields.url_rewrites.description",
        leftLabel: "connectors.web.fields.url_rewrites.leftLabel",
        rightLabel: "connectors.web.fields.url_rewrites.rightLabel",
        leftPlaceholder: "connectors.web.fields.url_rewrites.leftPlaceholder",
        rightPlaceholder: "connectors.web.fields.url_rewrites.rightPlaceholder",
        default: [],
      },
    ],
    overrideDefaultFreq: 60 * 60 * 24,
  },
  lumapps: {
    description: "connectors.lumapps.description",
    values: [
      {
        type: "text",
        label: "connectors.lumapps.fields.base_url.label",
        name: "base_url",
        optional: false,
        description: "connectors.lumapps.fields.base_url.description",
      },
      {
        type: "text",
        label: "connectors.lumapps.fields.organization_id.label",
        name: "organization_id",
        optional: false,
        description: "connectors.lumapps.fields.organization_id.description",
      },
    ],
    advanced_values: [
      {
        type: "list",
        label: "connectors.lumapps.fields.instance_ids.label",
        name: "instance_ids",
        optional: true,
        description: "connectors.lumapps.fields.instance_ids.description",
      },
      {
        type: "list",
        label: "connectors.lumapps.fields.custom_content_types.label",
        name: "custom_content_types",
        optional: true,
        description:
          "connectors.lumapps.fields.custom_content_types.description",
      },
      {
        type: "text",
        label: "connectors.lumapps.fields.lang.label",
        name: "lang",
        optional: true,
        default: "en",
        description: "connectors.lumapps.fields.lang.description",
      },
    ],
  },
  youtrack: {
    description: "connectors.youtrack.description",
    values: [
      {
        type: "text",
        label: "connectors.youtrack.fields.base_url.label",
        name: "base_url",
        optional: false,
        description: "connectors.youtrack.fields.base_url.description",
      },
      {
        type: "list",
        label: "connectors.youtrack.fields.projects.label",
        name: "projects",
        optional: true,
        description: "connectors.youtrack.fields.projects.description",
      },
    ],
    advanced_values: [],
  },
  github: {
    description: "connectors.github.description",
    values: [
      {
        type: "text",
        label: "connectors.github.fields.github_base_url.label",
        name: "github_base_url",
        optional: true,
        description: "connectors.github.fields.github_base_url.description",
        placeholder: "connectors.github.fields.github_base_url.placeholder",
        subDescription: "siteUrl",
      },
      {
        type: "text",
        label: "connectors.github.fields.repo_owner.label",
        name: "repo_owner",
        optional: false,
      },
      {
        type: "tab",
        name: "github_mode",
        label: "connectors.github.fields.github_mode.label",
        optional: true,
        tabs: [
          {
            value: "repo",
            label: "connectors.github.fields.github_mode.tabs.repo.label",
            fields: [
              {
                type: "text",
                label: "connectors.github.fields.repositories.label",
                name: "repositories",
                optional: false,
                description:
                  "connectors.github.fields.repositories.description",
              },
            ],
          },
          {
            value: "everything",
            label: "connectors.github.fields.github_mode.tabs.everything.label",
            fields: [
              {
                type: "string_tab",
                label: "connectors.github.fields.everything.label",
                name: "everything",
                description: "connectors.github.fields.everything.description",
              },
            ],
          },
        ],
      },
      {
        type: "checkbox",
        label: "connectors.github.fields.include_prs.label",
        description: "connectors.github.fields.include_prs.description",
        name: "include_prs",
        optional: true,
      },
      {
        type: "checkbox",
        label: "connectors.github.fields.include_issues.label",
        name: "include_issues",
        description: "connectors.github.fields.include_issues.description",
        optional: true,
      },
      {
        type: "checkbox",
        label: "connectors.github.fields.include_files.label",
        name: "include_files",
        description: "connectors.github.fields.include_files.description",
        optional: true,
      },
    ],
    advanced_values: [
      {
        type: "text",
        label: "connectors.github.fields.branch.label",
        name: "branch",
        optional: true,
        description: "connectors.github.fields.branch.description",
      },
    ],
  },
  testrail: {
    description: "connectors.testrail.description",
    values: [
      {
        type: "text",
        label: "connectors.testrail.fields.testrail_base_url.label",
        name: "testrail_base_url",
        optional: false,
        placeholder: "connectors.testrail.fields.testrail_base_url.placeholder",
        subDescription: "siteUrl",
      },
      {
        type: "text",
        label: "connectors.testrail.fields.project_ids.label",
        name: "project_ids",
        optional: true,
        description: "connectors.testrail.fields.project_ids.description",
      },
    ],
    advanced_values: [
      {
        type: "number",
        label: "connectors.testrail.fields.cases_page_size.label",
        name: "cases_page_size",
        optional: true,
        description: "connectors.testrail.fields.cases_page_size.description",
      },
      {
        type: "number",
        label: "connectors.testrail.fields.max_pages.label",
        name: "max_pages",
        optional: true,
        description: "connectors.testrail.fields.max_pages.description",
      },
      {
        type: "number",
        label: "connectors.testrail.fields.skip_doc_absolute_chars.label",
        name: "skip_doc_absolute_chars",
        optional: true,
        description:
          "connectors.testrail.fields.skip_doc_absolute_chars.description",
      },
    ],
  },
  gitlab: {
    description: "connectors.gitlab.description",
    values: [
      {
        type: "text",
        label: "connectors.gitlab.fields.gitlab_url.label",
        name: "gitlab_url",
        optional: false,
        placeholder: "connectors.gitlab.fields.gitlab_url.placeholder",
        subDescription: "siteUrl",
      },
      {
        type: "text",
        label: "connectors.gitlab.fields.project_owner.label",
        name: "project_owner",
        optional: false,
      },
      {
        type: "text",
        label: "connectors.gitlab.fields.project_name.label",
        name: "project_name",
        optional: false,
      },
    ],
    advanced_values: [
      {
        type: "checkbox",
        label: "connectors.gitlab.fields.include_mrs.label",
        name: "include_mrs",
        description: "connectors.gitlab.fields.include_mrs.description",
        default: true,
      },
      {
        type: "checkbox",
        label: "connectors.gitlab.fields.include_issues.label",
        name: "include_issues",
        description: "connectors.gitlab.fields.include_issues.description",
        default: true,
      },
    ],
  },
  bitbucket: {
    description: "connectors.bitbucket.description",
    subtext: "connectors.bitbucket.subtext",
    values: [
      {
        type: "text",
        label: "connectors.bitbucket.fields.workspace.label",
        name: "workspace",
        optional: false,
        description: "connectors.bitbucket.fields.workspace.description",
      },
      {
        type: "tab",
        name: "bitbucket_mode",
        label: "connectors.bitbucket.fields.bitbucket_mode.label",
        optional: true,
        tabs: [
          {
            value: "repo",
            label: "connectors.bitbucket.fields.bitbucket_mode.tabs.repo.label",
            fields: [
              {
                type: "text",
                label: "connectors.bitbucket.fields.repositories.label",
                name: "repositories",
                optional: false,
                description:
                  "connectors.bitbucket.fields.repositories.description",
              },
            ],
          },
          {
            value: "project",
            label:
              "connectors.bitbucket.fields.bitbucket_mode.tabs.project.label",
            fields: [
              {
                type: "text",
                label: "connectors.bitbucket.fields.projects.label",
                name: "projects",
                optional: false,
                description: "connectors.bitbucket.fields.projects.description",
              },
            ],
          },
          {
            value: "workspace",
            label:
              "connectors.bitbucket.fields.bitbucket_mode.tabs.workspace.label",
            fields: [
              {
                type: "string_tab",
                label: "connectors.bitbucket.fields.workspace_tab.label",
                name: "workspace_tab",
                description:
                  "connectors.bitbucket.fields.workspace_tab.description",
              },
            ],
          },
        ],
      },
    ],
    advanced_values: [],
  },
  gitbook: {
    description: "connectors.gitbook.description",
    values: [
      {
        type: "text",
        label: "connectors.gitbook.fields.space_id.label",
        name: "space_id",
        optional: false,
        description: "connectors.gitbook.fields.space_id.description",
      },
    ],
    advanced_values: [],
  },
  google_drive: {
    description: "connectors.google_drive.description",
    configFromCredential: (credential) => ({
      credential_kind: googleCredentialKind(credential),
    }),
    values: [
      {
        type: "text",
        label: "connectors.google_drive.fields.credential_kind.label",
        name: "credential_kind",
        optional: true,
        hidden: true,
      },
      {
        type: "tab",
        name: "indexing_scope",
        optional: true,
        tabs: [
          {
            value: OneDriveScope.General,
            label:
              "connectors.google_drive.fields.indexing_scope.tabs.General.label",
            fields: [
              {
                type: "checkbox",
                label:
                  "connectors.google_drive.fields.include_shared_drives.label",
                description: (currentCredential) => {
                  return currentCredential?.credential_json?.google_tokens
                    ? "connectors.google_drive.fields.include_shared_drives.description.oauth"
                    : "connectors.google_drive.fields.include_shared_drives.description.serviceAccount";
                },
                name: "include_shared_drives",
                default: false,
              },
              {
                type: "checkbox",
                label: (currentCredential) => {
                  return currentCredential?.credential_json?.google_tokens
                    ? "connectors.google_drive.fields.include_my_drives.label.oauth"
                    : "connectors.google_drive.fields.include_my_drives.label.serviceAccount";
                },
                description: (currentCredential) => {
                  return currentCredential?.credential_json?.google_tokens
                    ? "connectors.google_drive.fields.include_my_drives.description.oauth"
                    : "connectors.google_drive.fields.include_my_drives.description.serviceAccount";
                },
                name: "include_my_drives",
                default: false,
              },
              {
                type: "checkbox",
                description:
                  "connectors.google_drive.fields.include_files_shared_with_me.description",
                label:
                  "connectors.google_drive.fields.include_files_shared_with_me.label",
                name: "include_files_shared_with_me",
                visibleCondition: (values, currentCredential) =>
                  currentCredential?.credential_json?.google_tokens,
                default: false,
              },
            ],
          },
          {
            value: OneDriveScope.Specific,
            label:
              "connectors.google_drive.fields.indexing_scope.tabs.Specific.label",
            fields: [
              {
                type: "text",
                description: (currentCredential) => {
                  return currentCredential?.credential_json?.google_tokens
                    ? "connectors.google_drive.fields.shared_drive_urls.description.oauth"
                    : "connectors.google_drive.fields.shared_drive_urls.description.serviceAccount";
                },
                label: "connectors.google_drive.fields.shared_drive_urls.label",
                name: "shared_drive_urls",
                default: "",
                isTextArea: true,
              },
              {
                type: "text",
                description:
                  "connectors.google_drive.fields.shared_folder_urls.description",
                label:
                  "connectors.google_drive.fields.shared_folder_urls.label",
                name: "shared_folder_urls",
                default: "",
                isTextArea: true,
              },
              {
                type: "text",
                description:
                  "connectors.google_drive.fields.my_drive_emails.description",
                label: "connectors.google_drive.fields.my_drive_emails.label",
                name: "my_drive_emails",
                visibleCondition: (values, currentCredential) =>
                  !currentCredential?.credential_json?.google_tokens,
                default: "",
                isTextArea: true,
              },
            ],
          },
        ],
        defaultTab: OneDriveScope.General,
      },
    ],
    advanced_values: [
      {
        type: "text",
        description:
          "connectors.google_drive.fields.specific_user_emails.description",
        label: "connectors.google_drive.fields.specific_user_emails.label",
        name: "specific_user_emails",
        optional: true,
        default: "",
        isTextArea: true,
        visibleCondition: (values, currentCredential) =>
          !currentCredential?.credential_json?.google_tokens,
      },
      {
        type: "checkbox",
        label: "connectors.google_drive.fields.exclude_domain_link_only.label",
        description:
          "connectors.google_drive.fields.exclude_domain_link_only.description",
        name: "exclude_domain_link_only",
        optional: true,
        default: false,
      },
    ],
  },
  onedrive: buildOneDriveConfiguration(ONE_DRIVE_TRANSLATION_KEYS),
  gmail: {
    description: "connectors.gmail.description",
    values: [],
    advanced_values: [],
  },
  bookstack: {
    description: "connectors.bookstack.description",
    values: [
      {
        type: "text",
        label: "connectors.bookstack.fields.bookstack_base_url.label",
        name: "bookstack_base_url",
        optional: false,
        placeholder:
          "connectors.bookstack.fields.bookstack_base_url.placeholder",
        subDescription: "siteUrl",
      },
    ],
    advanced_values: [],
  },
  outline: {
    description: "connectors.outline.description",
    values: [
      {
        type: "text",
        label: "connectors.outline.fields.outline_base_url.label",
        name: "outline_base_url",
        optional: false,
        placeholder: "connectors.outline.fields.outline_base_url.placeholder",
        subDescription: "siteUrl",
      },
    ],
    advanced_values: [],
  },
  confluence: {
    description: "connectors.confluence.description",
    initialConnectorName: "cloud_name",
    values: [
      {
        type: "checkbox",
        label: "connectors.confluence.fields.is_cloud.label",
        name: "is_cloud",
        optional: false,
        default: true,
        tabLabels: {
          true: "confluenceCloud",
          false: "confluenceDataCenter",
        },
        description: "connectors.confluence.fields.is_cloud.description",
        // An OAuth credential is for Confluence Cloud only.
        initial: (currentCredential) =>
          currentCredential?.credential_json?.confluence_refresh_token
            ? true
            : undefined,
        disabled: (currentCredential) => {
          if (currentCredential?.credential_json?.confluence_refresh_token) {
            return true;
          }
          return false;
        },
      },
      {
        type: "text",
        label: "connectors.confluence.fields.wiki_base.label",
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
        placeholder: "connectors.confluence.fields.wiki_base.placeholder",
        subDescription: "siteUrl",
      },
      ATLASSIAN_SCOPED_TOKEN_FIELD,
      {
        type: "tab",
        name: "indexing_scope",
        optional: true,
        tabs: [
          {
            value: "everything",
            label:
              "connectors.confluence.fields.indexing_scope.tabs.everything.label",
            fields: [
              {
                type: "string_tab",
                label: "connectors.confluence.fields.everything.label",
                name: "everything",
                description:
                  "connectors.confluence.fields.everything.description",
              },
            ],
          },
          {
            value: "space",
            label:
              "connectors.confluence.fields.indexing_scope.tabs.space.label",
            fields: [
              {
                type: "text",
                label: "connectors.confluence.fields.space.label",
                name: "space",
                default: "",
                description: "connectors.confluence.fields.space.description",
              },
            ],
          },
          {
            value: "page",
            label:
              "connectors.confluence.fields.indexing_scope.tabs.page.label",
            fields: [
              {
                type: "text",
                label: "connectors.confluence.fields.page_id.label",
                name: "page_id",
                default: "",
                description: "connectors.confluence.fields.page_id.description",
              },
              {
                type: "checkbox",
                label: "connectors.confluence.fields.index_recursively.label",
                name: "index_recursively",
                description:
                  "connectors.confluence.fields.index_recursively.description",
                optional: false,
                default: true,
              },
            ],
          },
          {
            value: "cql",
            label: "connectors.confluence.fields.indexing_scope.tabs.cql.label",
            fields: [
              {
                type: "text",
                label: "connectors.confluence.fields.cql_query.label",
                name: "cql_query",
                default: "",
                description:
                  "connectors.confluence.fields.cql_query.description",
              },
            ],
          },
        ],
        defaultTab: "space",
      },
      buildIncludeAttachmentsOption(true),
    ],
    advanced_values: [],
  },
  jira: {
    description: "connectors.jira.description",
    subtext: "connectors.jira.subtext",
    values: [
      {
        type: "text",
        label: "connectors.jira.fields.jira_base_url.label",
        name: "jira_base_url",
        optional: false,
        placeholder: "connectors.jira.fields.jira_base_url.placeholder",
        subDescription: "siteUrl",
      },
      ATLASSIAN_SCOPED_TOKEN_FIELD,
      {
        type: "tab",
        name: "indexing_scope",
        optional: true,
        tabs: [
          {
            value: "everything",
            label:
              "connectors.jira.fields.indexing_scope.tabs.everything.label",
            fields: [
              {
                type: "string_tab",
                label: "connectors.jira.fields.everything.label",
                name: "everything",
                description: "connectors.jira.fields.everything.description",
              },
            ],
          },
          {
            value: "project",
            label: "connectors.jira.fields.indexing_scope.tabs.project.label",
            fields: [
              {
                type: "text",
                label: "connectors.jira.fields.project_key.label",
                name: "project_key",
                description: "connectors.jira.fields.project_key.description",
              },
            ],
          },
          {
            value: "jql",
            label: "connectors.jira.fields.indexing_scope.tabs.jql.label",
            fields: [
              {
                type: "text",
                label: "connectors.jira.fields.jql_query.label",
                name: "jql_query",
                description: "connectors.jira.fields.jql_query.description",
              },
            ],
          },
        ],
        defaultTab: "everything",
      },
      {
        type: "list",
        label: "connectors.jira.fields.comment_email_blacklist.label",
        name: "comment_email_blacklist",
        description:
          "connectors.jira.fields.comment_email_blacklist.description",
        optional: true,
      },
    ],
    advanced_values: [],
  },
  jira_service_management: {
    description: "Configure Jira Service Management connector",
    subtext: "Index tickets from one Jira Service Management project.",
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
        type: "text",
        query: "Enter the service desk project key:",
        label: "Project Key",
        name: "project_key",
        optional: false,
        description:
          "The key of the Jira Service Management project to index (e.g., SUP).",
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
        type: "text",
        query: "Enter an optional JQL filter:",
        label: "JQL Filter",
        name: "jql_query",
        optional: true,
        description:
          "Add conditions to limit tickets. The selected project remains in scope.",
      },
      {
        type: "list",
        query: "Enter email addresses to skip in comments:",
        label: "Comment Email Blacklist",
        name: "comment_email_blacklist",
        optional: true,
        description: "Comments from these addresses will not be indexed.",
      },
    ],
    advanced_values: [],
  },
  salesforce: {
    description: "connectors.salesforce.description",
    values: [
      {
        type: "tab",
        name: "salesforce_config_type",
        label: "connectors.salesforce.fields.salesforce_config_type.label",
        optional: true,
        tabs: [
          {
            value: "simple",
            label:
              "connectors.salesforce.fields.salesforce_config_type.tabs.simple.label",
            fields: [
              {
                type: "list",
                label: "connectors.salesforce.fields.requested_objects.label",
                name: "requested_objects",
                optional: true,
                description:
                  "connectors.salesforce.fields.requested_objects.description",
              },
            ],
          },
          {
            value: "advanced",
            label:
              "connectors.salesforce.fields.salesforce_config_type.tabs.advanced.label",
            fields: [
              {
                type: "text",
                label: "connectors.salesforce.fields.custom_query_config.label",
                name: "custom_query_config",
                optional: true,
                isTextArea: true,
                description:
                  "connectors.salesforce.fields.custom_query_config.description",
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
    description: "connectors.sharepoint.description",
    values: [
      {
        type: "list",
        label: "connectors.sharepoint.fields.sites.label",
        name: "sites",
        optional: true,
        description: "connectors.sharepoint.fields.sites.description",
      },
    ],
    advanced_values: [
      {
        type: "checkbox",
        label: "connectors.sharepoint.fields.include_site_documents.label",
        name: "include_site_documents",
        optional: true,
        default: true,
        description:
          "connectors.sharepoint.fields.include_site_documents.description",
      },
      {
        type: "checkbox",
        label: "connectors.sharepoint.fields.include_site_pages.label",
        name: "include_site_pages",
        optional: true,
        default: true,
        description:
          "connectors.sharepoint.fields.include_site_pages.description",
      },
      {
        type: "checkbox",
        label:
          "connectors.sharepoint.fields.treat_sharing_link_as_public.label",
        description:
          "connectors.sharepoint.fields.treat_sharing_link_as_public.description",
        name: "treat_sharing_link_as_public",
        optional: true,
        default: false,
      },
      {
        type: "list",
        label: "connectors.sharepoint.fields.excluded_sites.label",
        name: "excluded_sites",
        optional: true,
        description: "connectors.sharepoint.fields.excluded_sites.description",
      },
      {
        type: "list",
        label: "connectors.sharepoint.fields.excluded_paths.label",
        name: "excluded_paths",
        optional: true,
        description: "connectors.sharepoint.fields.excluded_paths.description",
      },
      {
        type: "text",
        label: "connectors.sharepoint.fields.authority_host.label",
        name: "authority_host",
        optional: true,
        default: "https://login.microsoftonline.com",
        description: "connectors.sharepoint.fields.authority_host.description",
      },
      {
        type: "text",
        label: "connectors.sharepoint.fields.graph_api_host.label",
        name: "graph_api_host",
        optional: true,
        default: "https://graph.microsoft.com",
        description: "connectors.sharepoint.fields.graph_api_host.description",
      },
      {
        type: "text",
        label: "connectors.sharepoint.fields.sharepoint_domain_suffix.label",
        name: "sharepoint_domain_suffix",
        optional: true,
        default: "sharepoint.com",
        description:
          "connectors.sharepoint.fields.sharepoint_domain_suffix.description",
      },
    ],
  },
  teams: {
    description: "connectors.teams.description",
    values: [
      {
        type: "list",
        label: "connectors.teams.fields.teams.label",
        name: "teams",
        optional: true,
        description: "connectors.teams.fields.teams.description",
      },
      buildIncludeAttachmentsOption(
        false,
        "connectors.teams.fields.include_attachments.description"
      ),
      {
        type: "checkbox",
        label: "connectors.teams.fields.include_inline_images.label",
        name: "include_inline_images",
        description:
          "connectors.teams.fields.include_inline_images.description",
        default: false,
      },
      {
        type: "checkbox",
        label: "connectors.teams.fields.include_meeting_transcripts.label",
        name: "include_meeting_transcripts",
        description:
          "connectors.teams.fields.include_meeting_transcripts.description",
        default: false,
      },
      {
        type: "checkbox",
        label: "connectors.teams.fields.include_meeting_chats.label",
        name: "include_meeting_chats",
        description:
          "connectors.teams.fields.include_meeting_chats.description",
        default: false,
      },
      {
        type: "list",
        label: "connectors.teams.fields.meeting_organizers.label",
        name: "meeting_organizers",
        optional: true,
        description: "connectors.teams.fields.meeting_organizers.description",
      },
    ],
    advanced_values: [
      {
        type: "text",
        label: "connectors.teams.fields.authority_host.label",
        name: "authority_host",
        optional: true,
        default: "https://login.microsoftonline.com",
        description: "connectors.teams.fields.authority_host.description",
      },
      {
        type: "text",
        label: "connectors.teams.fields.graph_api_host.label",
        name: "graph_api_host",
        optional: true,
        default: "https://graph.microsoft.com",
        description: "connectors.teams.fields.graph_api_host.description",
      },
    ],
  },
  outlook: {
    description: "connectors.outlook.description",
    values: [
      {
        type: "list",
        label: "connectors.outlook.fields.mailboxes.label",
        name: "mailboxes",
        optional: true,
        description: "connectors.outlook.fields.mailboxes.description",
      },
      {
        type: "list",
        label: "connectors.outlook.fields.mailbox_groups.label",
        name: "mailbox_groups",
        optional: true,
        description: "connectors.outlook.fields.mailbox_groups.description",
      },
      buildIncludeAttachmentsOption(
        false,
        "connectors.outlook.fields.include_attachments.description"
      ),
      {
        type: "checkbox",
        label: "connectors.outlook.fields.include_calendar.label",
        name: "include_calendar",
        description: "connectors.outlook.fields.include_calendar.description",
        default: false,
      },
    ],
    advanced_values: [
      {
        type: "list",
        label: "connectors.outlook.fields.excluded_folders.label",
        name: "excluded_folders",
        optional: true,
        description: "connectors.outlook.fields.excluded_folders.description",
      },
      {
        type: "number",
        label: "connectors.outlook.fields.calendar_past_days.label",
        name: "calendar_past_days",
        optional: true,
        default: 365,
        description: "connectors.outlook.fields.calendar_past_days.description",
      },
      {
        type: "number",
        label: "connectors.outlook.fields.calendar_future_days.label",
        name: "calendar_future_days",
        optional: true,
        default: 180,
        description:
          "connectors.outlook.fields.calendar_future_days.description",
      },
      {
        type: "text",
        label: "connectors.outlook.fields.authority_host.label",
        name: "authority_host",
        optional: true,
        default: "https://login.microsoftonline.com",
        description: "connectors.outlook.fields.authority_host.description",
      },
      {
        type: "text",
        label: "connectors.outlook.fields.graph_api_host.label",
        name: "graph_api_host",
        optional: true,
        default: "https://graph.microsoft.com",
        description: "connectors.outlook.fields.graph_api_host.description",
      },
    ],
  },
  discourse: {
    description: "connectors.discourse.description",
    values: [
      {
        type: "text",
        label: "connectors.discourse.fields.base_url.label",
        name: "base_url",
        optional: false,
      },
      {
        type: "list",
        label: "connectors.discourse.fields.categories.label",
        name: "categories",
        optional: true,
      },
    ],
    advanced_values: [],
  },
  drupal_wiki: {
    description: "connectors.drupal_wiki.description",
    values: [
      {
        type: "text",
        label: "connectors.drupal_wiki.fields.base_url.label",
        name: "base_url",
        optional: false,
        description: "connectors.drupal_wiki.fields.base_url.description",
      },
      {
        type: "tab",
        name: "indexing_scope",
        label: "connectors.drupal_wiki.fields.indexing_scope.label",
        optional: true,
        tabs: [
          {
            value: "everything",
            label:
              "connectors.drupal_wiki.fields.indexing_scope.tabs.everything.label",
            fields: [
              {
                type: "string_tab",
                label:
                  "connectors.drupal_wiki.fields.everything_description.label",
                name: "everything_description",
                description:
                  "connectors.drupal_wiki.fields.everything_description.description",
              },
            ],
          },
          {
            value: "specific",
            label:
              "connectors.drupal_wiki.fields.indexing_scope.tabs.specific.label",
            fields: [
              {
                type: "list",
                label: "connectors.drupal_wiki.fields.spaces.label",
                name: "spaces",
                description: "connectors.drupal_wiki.fields.spaces.description",
                optional: true,
                transform: (values: string[]) =>
                  values.filter((value) => /^\d+$/.test(value.trim())),
              },
              {
                type: "list",
                label: "connectors.drupal_wiki.fields.pages.label",
                name: "pages",
                description: "connectors.drupal_wiki.fields.pages.description",
                optional: true,
                transform: (values: string[]) =>
                  values.filter((value) => /^\d+$/.test(value.trim())),
              },
            ],
          },
        ],
      },
      buildIncludeAttachmentsOption(false),
    ],
    advanced_values: [],
  },
  axero: {
    description: "connectors.axero.description",
    values: [
      {
        type: "text",
        label: "connectors.axero.fields.base_url.label",
        name: "base_url",
        optional: false,
        placeholder: "connectors.axero.fields.base_url.placeholder",
        subDescription: "siteUrl",
      },
      {
        type: "list",
        label: "connectors.axero.fields.spaces.label",
        name: "spaces",
        optional: true,
        description: "connectors.axero.fields.spaces.description",
      },
    ],
    advanced_values: [],
    overrideDefaultFreq: 60 * 60 * 24,
  },
  productboard: {
    description: "connectors.productboard.description",
    values: [],
    advanced_values: [],
  },
  slack: {
    description: "connectors.slack.description",
    values: [],
    advanced_values: [
      {
        type: "list",
        label: "connectors.slack.fields.channels.label",
        name: "channels",
        description: "connectors.slack.fields.channels.description",
        optional: true,
        optionsFinding: "readable_channels",
        plainListCondition: (values) => values.channel_regex_enabled === true,
      },
      {
        type: "checkbox",
        label: "connectors.slack.fields.channel_regex_enabled.label",
        name: "channel_regex_enabled",
        description:
          "connectors.slack.fields.channel_regex_enabled.description",
        optional: true,
      },
      {
        type: "list",
        label: "connectors.slack.fields.exclude_channels.label",
        name: "exclude_channels",
        description: "connectors.slack.fields.exclude_channels.description",
        optional: true,
        optionsFinding: "readable_channels",
        plainListCondition: (values) =>
          values.exclude_channel_regex_enabled === true,
      },
      {
        type: "checkbox",
        label: "connectors.slack.fields.exclude_channel_regex_enabled.label",
        name: "exclude_channel_regex_enabled",
        description:
          "connectors.slack.fields.exclude_channel_regex_enabled.description",
        optional: true,
      },
      {
        type: "checkbox",
        label: "connectors.slack.fields.include_bot_messages.label",
        name: "include_bot_messages",
        description: "connectors.slack.fields.include_bot_messages.description",
        optional: true,
      },
    ],
  },
  slab: {
    description: "connectors.slab.description",
    values: [
      {
        type: "text",
        label: "connectors.slab.fields.base_url.label",
        name: "base_url",
        optional: false,
        description: "connectors.slab.fields.base_url.description",
      },
    ],
    advanced_values: [],
  },
  guru: {
    description: "connectors.guru.description",
    values: [],
    advanced_values: [],
  },
  gong: {
    description: "connectors.gong.description",
    values: [
      {
        type: "text",
        label: "connectors.gong.fields.gong_base_url.label",
        name: "gong_base_url",
        optional: true,
        description: "connectors.gong.fields.gong_base_url.description",
        placeholder: "connectors.gong.fields.gong_base_url.placeholder",
        subDescription: "siteUrl",
      },
      {
        type: "list",
        label: "connectors.gong.fields.workspaces.label",
        name: "workspaces",
        optional: true,
        description: "connectors.gong.fields.workspaces.description",
      },
    ],
    advanced_values: [],
  },
  loopio: {
    description: "connectors.loopio.description",
    values: [
      {
        type: "text",
        label: "connectors.loopio.fields.loopio_subdomain.label",
        name: "loopio_subdomain",
        optional: false,
        description: "connectors.loopio.fields.loopio_subdomain.description",
        placeholder: "connectors.loopio.fields.loopio_subdomain.placeholder",
      },
      {
        type: "text",
        label: "connectors.loopio.fields.loopio_stack_name.label",
        name: "loopio_stack_name",
        description: "connectors.loopio.fields.loopio_stack_name.description",
        optional: true,
      },
    ],
    advanced_values: [],
    overrideDefaultFreq: 60 * 60 * 24,
  },
  file: {
    description: "connectors.file.description",
    values: [
      {
        type: "file",
        label: "connectors.file.fields.file_locations.label",
        name: "file_locations",
        optional: false,
      },
    ],
    advanced_values: [],
  },
  zulip: {
    description: "connectors.zulip.description",
    values: [
      {
        type: "text",
        label: "connectors.zulip.fields.realm_name.label",
        name: "realm_name",
        optional: false,
      },
      {
        type: "text",
        label: "connectors.zulip.fields.realm_url.label",
        name: "realm_url",
        optional: false,
      },
    ],
    advanced_values: [],
  },
  coda: {
    description: "connectors.coda.description",
    values: [],
    advanced_values: [],
  },
  notion: {
    description: "connectors.notion.description",
    values: [
      {
        type: "text",
        label: "connectors.notion.fields.root_page_id.label",
        name: "root_page_id",
        optional: true,
        description: "connectors.notion.fields.root_page_id.description",
      },
    ],
    advanced_values: [],
  },
  hubspot: {
    description: "connectors.hubspot.description",
    values: [
      {
        type: "multiselect",
        label: "connectors.hubspot.fields.object_types.label",
        name: "object_types",
        options: [
          {
            name: "connectors.hubspot.fields.object_types.options.tickets",
            value: "tickets",
          },
          {
            name: "connectors.hubspot.fields.object_types.options.companies",
            value: "companies",
          },
          {
            name: "connectors.hubspot.fields.object_types.options.deals",
            value: "deals",
          },
          {
            name: "connectors.hubspot.fields.object_types.options.contacts",
            value: "contacts",
          },
        ],
        default: ["tickets", "companies", "deals", "contacts"],
        description: "connectors.hubspot.fields.object_types.description",
        optional: false,
      },
    ],
    advanced_values: [],
  },
  document360: {
    description: "connectors.document360.description",
    values: [
      {
        type: "text",
        label: "connectors.document360.fields.workspace.label",
        name: "workspace",
        optional: false,
      },
      {
        type: "list",
        label: "connectors.document360.fields.categories.label",
        name: "categories",
        optional: true,
        description: "connectors.document360.fields.categories.description",
      },
    ],
    advanced_values: [],
  },
  clickup: {
    description: "connectors.clickup.description",
    values: [
      {
        type: "select",
        label: "connectors.clickup.fields.connector_type.label",
        name: "connector_type",
        optional: false,
        options: [
          {
            name: "connectors.clickup.fields.connector_type.options.list",
            value: "list",
          },
          {
            name: "connectors.clickup.fields.connector_type.options.folder",
            value: "folder",
          },
          {
            name: "connectors.clickup.fields.connector_type.options.space",
            value: "space",
          },
          {
            name: "connectors.clickup.fields.connector_type.options.workspace",
            value: "workspace",
          },
        ],
      },
      {
        type: "list",
        label: "connectors.clickup.fields.connector_ids.label",
        name: "connector_ids",
        description: "connectors.clickup.fields.connector_ids.description",
        optional: true,
      },
      {
        type: "checkbox",
        label: "connectors.clickup.fields.retrieve_task_comments.label",
        name: "retrieve_task_comments",
        description:
          "connectors.clickup.fields.retrieve_task_comments.description",
        optional: false,
      },
    ],
    advanced_values: [],
  },
  google_sites: {
    description: "connectors.google_sites.description",
    values: [
      {
        type: "text",
        label: "connectors.google_sites.fields.base_url.label",
        name: "base_url",
        optional: false,
        // The published site's root; each page's link is this plus its path.
        placeholder: "connectors.google_sites.fields.base_url.placeholder",
      },
      {
        type: "file",
        label: "connectors.google_sites.fields.file_locations.label",
        name: "file_locations",
        optional: false,
        description:
          "connectors.google_sites.fields.file_locations.description",
        multiple: false,
        accept: ".zip",
      },
    ],
    advanced_values: [],
  },
  zendesk: {
    description: "connectors.zendesk.description",
    values: [
      {
        type: "text",
        label: "connectors.zendesk.fields.zendesk_subdomain.label",
        name: "zendesk_subdomain",
        optional: false,
        description: "connectors.zendesk.fields.zendesk_subdomain.description",
        placeholder: "connectors.zendesk.fields.zendesk_subdomain.placeholder",
      },
      {
        type: "select",
        label: "connectors.zendesk.fields.content_type.label",
        name: "content_type",
        optional: false,
        options: [
          {
            name: "connectors.zendesk.fields.content_type.options.articles",
            value: "articles",
          },
          {
            name: "connectors.zendesk.fields.content_type.options.tickets",
            value: "tickets",
          },
        ],
        default: "articles",
      },
    ],
    advanced_values: [
      {
        type: "number",
        label: "connectors.zendesk.fields.calls_per_minute.label",
        name: "calls_per_minute",
        optional: true,
        description: "connectors.zendesk.fields.calls_per_minute.description",
      },
    ],
  },
  linear: buildLinearConfiguration(LINEAR_TRANSLATION_KEYS),
  box: {
    description: "connectors.box.description",
    values: [
      {
        type: "list",
        label: "connectors.box.fields.folder_ids.label",
        name: "folder_ids",
        description: "connectors.box.fields.folder_ids.description",
        optional: true,
      },
    ],
    advanced_values: [
      {
        type: "checkbox",
        label: "connectors.box.fields.include_web_links.label",
        name: "include_web_links",
        description: "connectors.box.fields.include_web_links.description",
        optional: true,
      },
    ],
  },
  dropbox: {
    description: "connectors.dropbox.description",
    values: [],
    advanced_values: [],
  },
  s3: {
    description: "connectors.s3.description",
    values: [
      {
        type: "text",
        label: "connectors.s3.fields.bucket_name.label",
        name: "bucket_name",
        optional: false,
      },
      {
        type: "text",
        label: "connectors.s3.fields.prefix.label",
        name: "prefix",
        optional: true,
      },
      {
        type: "text",
        label: "connectors.s3.fields.region_name.label",
        name: "region_name",
        description: "connectors.s3.fields.region_name.description",
        optional: true,
      },
      {
        type: "text",
        label: "connectors.s3.fields.bucket_type.label",
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
    description: "connectors.r2.description",
    values: [
      {
        type: "text",
        label: "connectors.r2.fields.bucket_name.label",
        name: "bucket_name",
        optional: false,
      },
      {
        type: "text",
        label: "connectors.r2.fields.prefix.label",
        name: "prefix",
        optional: true,
      },
      {
        type: "checkbox",
        label: "connectors.r2.fields.european_residency.label",
        name: "european_residency",
        description: "connectors.r2.fields.european_residency.description",
        optional: true,
        default: false,
      },
      {
        type: "text",
        label: "connectors.r2.fields.bucket_type.label",
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
    description: "connectors.google_cloud_storage.description",
    values: [
      {
        type: "text",
        label: "connectors.google_cloud_storage.fields.bucket_name.label",
        name: "bucket_name",
        optional: false,
        description:
          "connectors.google_cloud_storage.fields.bucket_name.description",
      },
      {
        type: "text",
        label: "connectors.google_cloud_storage.fields.prefix.label",
        name: "prefix",
        optional: true,
      },
      {
        type: "text",
        label: "connectors.google_cloud_storage.fields.bucket_type.label",
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
    description: "connectors.oci_storage.description",
    values: [
      {
        type: "text",
        label: "connectors.oci_storage.fields.bucket_name.label",
        name: "bucket_name",
        optional: false,
      },
      {
        type: "text",
        label: "connectors.oci_storage.fields.prefix.label",
        name: "prefix",
        optional: true,
      },
      {
        type: "text",
        label: "connectors.oci_storage.fields.bucket_type.label",
        name: "bucket_type",
        optional: false,
        default: "oci_storage",
        hidden: true,
      },
    ],
    advanced_values: [],
  },
  wikipedia: {
    description: "connectors.wikipedia.description",
    values: [
      {
        type: "text",
        label: "connectors.wikipedia.fields.language_code.label",
        name: "language_code",
        optional: false,
        description: "connectors.wikipedia.fields.language_code.description",
      },
      {
        type: "list",
        label: "connectors.wikipedia.fields.categories.label",
        name: "categories",
        description: "connectors.wikipedia.fields.categories.description",
        optional: true,
      },
      {
        type: "list",
        label: "connectors.wikipedia.fields.pages.label",
        name: "pages",
        optional: true,
        description: "connectors.wikipedia.fields.pages.description",
      },
      {
        type: "number",
        label: "connectors.wikipedia.fields.recurse_depth.label",
        name: "recurse_depth",
        description: "connectors.wikipedia.fields.recurse_depth.description",
        optional: false,
      },
    ],
    advanced_values: [],
  },
  xenforo: {
    description: "connectors.xenforo.description",
    values: [
      {
        type: "text",
        label: "connectors.xenforo.fields.base_url.label",
        name: "base_url",
        optional: false,
        description: "connectors.xenforo.fields.base_url.description",
      },
    ],
    advanced_values: [],
  },
  asana: {
    description: "connectors.asana.description",
    values: [
      {
        type: "text",
        label: "connectors.asana.fields.asana_workspace_id.label",
        name: "asana_workspace_id",
        optional: false,
        description: "connectors.asana.fields.asana_workspace_id.description",
      },
      {
        type: "text",
        label: "connectors.asana.fields.asana_project_ids.label",
        name: "asana_project_ids",
        description: "connectors.asana.fields.asana_project_ids.description",
        optional: true,
      },
      {
        type: "text",
        label: "connectors.asana.fields.asana_team_id.label",
        name: "asana_team_id",
        optional: true,
        description: "connectors.asana.fields.asana_team_id.description",
      },
    ],
    advanced_values: [],
  },
  mediawiki: {
    description: "connectors.mediawiki.description",
    values: [
      {
        type: "text",
        label: "connectors.mediawiki.fields.language_code.label",
        name: "language_code",
        optional: false,
        description: "connectors.mediawiki.fields.language_code.description",
      },
      {
        type: "text",
        label: "connectors.mediawiki.fields.hostname.label",
        name: "hostname",
        optional: false,
      },
      {
        type: "list",
        label: "connectors.mediawiki.fields.categories.label",
        name: "categories",
        description: "connectors.mediawiki.fields.categories.description",
        optional: true,
      },
      {
        type: "list",
        label: "connectors.mediawiki.fields.pages.label",
        name: "pages",
        optional: true,
        description: "connectors.mediawiki.fields.pages.description",
      },
      {
        type: "number",
        label: "connectors.mediawiki.fields.recurse_depth.label",
        name: "recurse_depth",
        description: "connectors.mediawiki.fields.recurse_depth.description",
        optional: false,
      },
    ],
    advanced_values: [],
  },
  discord: {
    description: "connectors.discord.description",
    values: [],
    advanced_values: [
      {
        type: "list",
        label: "connectors.discord.fields.server_ids.label",
        name: "server_ids",
        description: "connectors.discord.fields.server_ids.description",
        optional: true,
      },
      {
        type: "list",
        label: "connectors.discord.fields.channel_names.label",
        name: "channel_names",
        description: "connectors.discord.fields.channel_names.description",
        optional: true,
      },
      {
        type: "text",
        label: "connectors.discord.fields.start_date.label",
        name: "start_date",
        description: "connectors.discord.fields.start_date.description",
        optional: true,
      },
    ],
  },
  freshdesk: {
    description: "connectors.freshdesk.description",
    values: [
      {
        type: "text",
        label: "connectors.freshdesk.fields.freshdesk_domain.label",
        name: "freshdesk_domain",
        optional: false,
        description: "connectors.freshdesk.fields.freshdesk_domain.description",
        placeholder: "connectors.freshdesk.fields.freshdesk_domain.placeholder",
      },
    ],
    advanced_values: [],
  },
  fireflies: {
    description: "connectors.fireflies.description",
    values: [],
    advanced_values: [],
  },
  zoom: {
    description: "connectors.zoom.description",
    subtext: "connectors.zoom.subtext",
    values: [
      // Two lists rather than one: the same number can be a legal meeting id
      // and a legal webinar id, so the list it is typed into says which.
      zoomMeetingIdsOption,
      zoomWebinarIdsOption,
      {
        type: "list",
        label: "connectors.zoom.fields.host_emails.label",
        name: "host_emails",
        optional: true,
        description: "connectors.zoom.fields.host_emails.description",
      },
      {
        type: "text",
        label: "connectors.zoom.fields.group_id.label",
        name: "group_id",
        optional: true,
        description: "connectors.zoom.fields.group_id.description",
      },
      {
        type: "checkbox",
        label: "connectors.zoom.fields.include_meetings.label",
        name: "include_meetings",
        description: "connectors.zoom.fields.include_meetings.description",
        default: true,
      },
      {
        type: "checkbox",
        label: "connectors.zoom.fields.include_webinars.label",
        name: "include_webinars",
        description: "connectors.zoom.fields.include_webinars.description",
        default: true,
      },
      {
        type: "checkbox",
        label: "connectors.zoom.fields.treat_link_access_as_public.label",
        name: "treat_link_access_as_public",
        description:
          "connectors.zoom.fields.treat_link_access_as_public.description",
        default: true,
      },
      {
        type: "select",
        label: "connectors.zoom.fields.plan_tier.label",
        name: "plan_tier",
        optional: false,
        options: [
          {
            name: "connectors.zoom.fields.plan_tier.options.pro",
            value: "pro",
          },
          {
            name: "connectors.zoom.fields.plan_tier.options.business_plus",
            value: "business_plus",
          },
        ],
        description: "connectors.zoom.fields.plan_tier.description",
      },
    ],
    advanced_values: [
      {
        type: "number",
        label: "connectors.zoom.fields.rate_limit_percent.label",
        name: "rate_limit_percent",
        optional: true,
        description: "connectors.zoom.fields.rate_limit_percent.description",
      },
    ],
  },
  braintrust: {
    description: "connectors.braintrust.description",
    values: [
      {
        type: "text",
        label: "connectors.braintrust.fields.project_name.label",
        name: "project_name",
        optional: true,
        description: "connectors.braintrust.fields.project_name.description",
      },
    ],
    advanced_values: [
      {
        type: "number",
        label:
          "connectors.braintrust.fields.experiment_row_lookback_days.label",
        name: "experiment_row_lookback_days",
        optional: true,
        default: 30,
        description:
          "connectors.braintrust.fields.experiment_row_lookback_days.description",
      },
    ],
  },
  canvas: {
    description: "connectors.canvas.description",
    values: [
      {
        type: "text",
        label: "connectors.canvas.fields.canvas_base_url.label",
        name: "canvas_base_url",
        optional: false,
        description: "connectors.canvas.fields.canvas_base_url.description",
      },
    ],
    advanced_values: [],
  },
  egnyte: {
    description: "connectors.egnyte.description",
    values: [
      {
        type: "text",
        label: "connectors.egnyte.fields.domain.label",
        name: "domain",
        optional: false,
        description: "connectors.egnyte.fields.domain.description",
        placeholder: "connectors.egnyte.fields.domain.placeholder",
      },
      {
        type: "text",
        label: "connectors.egnyte.fields.folder_path.label",
        name: "folder_path",
        optional: true,
        description: "connectors.egnyte.fields.folder_path.description",
      },
    ],
    advanced_values: [],
  },
  airtable: {
    description: "connectors.airtable.description",
    values: [
      {
        type: "tab",
        name: "airtable_scope",
        label: "connectors.airtable.fields.airtable_scope.label",
        optional: true,
        tabs: [
          {
            value: "everything",
            label:
              "connectors.airtable.fields.airtable_scope.tabs.everything.label",
            fields: [
              {
                type: "string_tab",
                label:
                  "connectors.airtable.fields.everything_description.label",
                name: "everything_description",
                description:
                  "connectors.airtable.fields.everything_description.description",
              },
            ],
          },
          {
            value: "specific",
            label:
              "connectors.airtable.fields.airtable_scope.tabs.specific.label",
            fields: [
              {
                type: "text",
                label: "connectors.airtable.fields.airtable_url.label",
                name: "airtable_url",
                optional: false,
                description:
                  "connectors.airtable.fields.airtable_url.description",
              },
              {
                type: "text",
                label: "connectors.airtable.fields.share_id.label",
                name: "share_id",
                optional: true,
                description: "connectors.airtable.fields.share_id.description",
              },
            ],
          },
        ],
      },
      {
        type: "checkbox",
        label:
          "connectors.airtable.fields.treat_all_non_attachment_fields_as_metadata.label",
        name: "treat_all_non_attachment_fields_as_metadata",
        description:
          "connectors.airtable.fields.treat_all_non_attachment_fields_as_metadata.description",
        optional: false,
      },
    ],
    advanced_values: [],
    overrideDefaultFreq: 60 * 60 * 24,
  },
  highspot: {
    description: "connectors.highspot.description",
    values: [
      {
        type: "text",
        label: "connectors.highspot.fields.highspot_url.label",
        name: "highspot_url",
        optional: false,
        placeholder: "connectors.highspot.fields.highspot_url.placeholder",
        subDescription: "siteUrl",
      },
      {
        type: "tab",
        name: "highspot_scope",
        label: "connectors.highspot.fields.highspot_scope.label",
        optional: true,
        tabs: [
          {
            value: "spots",
            label: "connectors.highspot.fields.highspot_scope.tabs.spots.label",
            fields: [
              {
                type: "list",
                label: "connectors.highspot.fields.spot_names.label",
                name: "spot_names",
                optional: false,
                description:
                  "connectors.highspot.fields.spot_names.description",
              },
            ],
          },
          {
            value: "everything",
            label:
              "connectors.highspot.fields.highspot_scope.tabs.everything.label",
            fields: [
              {
                type: "string_tab",
                label: "connectors.highspot.fields.everything.label",
                name: "everything",
                description:
                  "connectors.highspot.fields.everything.description",
              },
            ],
          },
        ],
      },
    ],
    advanced_values: [],
  },
  imap: {
    description: "connectors.imap.description",
    values: [
      {
        type: "text",
        label: "connectors.imap.fields.host.label",
        name: "host",
        optional: false,
        description: "connectors.imap.fields.host.description",
      },
      {
        type: "number",
        label: "connectors.imap.fields.port.label",
        name: "port",
        optional: true,
        default: 993,
        description: "connectors.imap.fields.port.description",
      },
      {
        type: "list",
        label: "connectors.imap.fields.mailboxes.label",
        name: "mailboxes",
        optional: true,
        description: "connectors.imap.fields.mailboxes.description",
      },
    ],
    advanced_values: [],
  },
};
export const defaultRefreshFreqMinutes = 30; // 30 minutes
// Match the backend minimums in Connector.validate_refresh_freq / validate_prune_freq.
const MIN_REFRESH_FREQ_SECONDS = 60;
const MIN_PRUNE_FREQ_SECONDS = 300;
export const MIN_REFRESH_FREQ_MINUTES = MIN_REFRESH_FREQ_SECONDS / 60;
// Rounded up to the prune input's 3 decimals, so it converts to at least 300s.
export const MIN_PRUNE_FREQ_HOURS =
  Math.ceil((MIN_PRUNE_FREQ_SECONDS / 3600) * 1000) / 1000;
// The columns are 32-bit integers of seconds; larger values fail on save.
const MAX_FREQ_SECONDS = 2_147_483_647;
export const MAX_REFRESH_FREQ_MINUTES = Math.floor(MAX_FREQ_SECONDS / 60);
export const MAX_PRUNE_FREQ_HOURS = Math.floor(MAX_FREQ_SECONDS / 3600);
