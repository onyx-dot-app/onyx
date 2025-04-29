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
    description: "Настроить веб-коннектор",
    values: [
      {
        type: "text",
        query:
          "Введите URL-адрес веб-сайта для копирования, например https://duc-smartsearch.ru/:",
        label: "URL",
        name: "base_url",
        optional: false,
      },
      {
        type: "select",
        query: "Выберите тип веб-коннектора:",
        label: "Метод сбора",
        name: "web_connector_type",
        options: [
          { name: "рекурсивный", value: "recursive" },
          { name: "одиночный", value: "single" },
          { name: "sitemap", value: "sitemap" },
        ],
      },
    ],
    advanced_values: [],
    overrideDefaultFreq: 60 * 60 * 24,
  },
  bookstack: {
    description: "Настроить коннектор Bookstack",
    values: [],
    advanced_values: [],
  },
  confluence: {
    description: "Настроить коннектор Confluence",
    values: [
      {
        type: "checkbox",
        query: "Это Confluence Cloud?",
        label: "Облачный",
        name: "is_cloud",
        optional: false,
        default: true,
        description:
          "Проверьте, является ли экземпляром Confluence Cloud, снимите флажок для Confluence Server/Data Center.",
      },
      {
        type: "text",
        query: "Введите URL-адрес вики:",
        label: "Wiki URL",
        name: "wiki_base",
        optional: false,
        description:
          " URL вашего экземпляра Confluence (например, https://your-domain.atlassian.net/wiki)",
      },
      {
        type: "tab",
        name: "indexing_scope",
        label: "Как нам следует индексировать ваш Confluence?",
        optional: true,
        tabs: [
          {
            value: "everything",
            label: "Все",
            fields: [
              {
                type: "string_tab",
                label: "Все",
                name: "everything",
                description:
                  "Этот коннектор проиндексирует все страницы, к которым есть доступ по предоставленным учетным данным!",
              },
            ],
          },
          {
            value: "space",
            label: "Пространство",
            fields: [
              {
                type: "text",
                query: "Введите пространство:",
                label: "Ключ пространства",
                name: "space",
                default: "",
                description:
                  "Ключ пространства Confluence для индексации (например, `KB`).",
              },
            ],
          },
          {
            value: "page",
            label: "Страница",
            fields: [
              {
                type: "text",
                query: "Введите идентификатор страницы:",
                label: "Идентификатор страницы",
                name: "page_id",
                default: "",
                description:
                  "Конкретный идентификатор страницы для индексации (например, `131368`)",
              },
              {
                type: "checkbox",
                query: "Следует ли индексировать страницы рекурсивно?",
                label: "Индексировать рекурсивно",
                name: "index_recursively",
                description:
                  "Если этот параметр установлен, мы будем индексировать страницу, указанную идентификатором страницы, а также все ее дочерние страницы.",
                optional: false,
                default: true,
              },
            ],
          },
          {
            value: "cql",
            label: "CQL-запрос",
            fields: [
              {
                type: "text",
                query: "Введите CQL-запрос (необязательно):",
                label: "CQL-запрос",
                name: "cql_query",
                default: "",
                description:
                  "ВАЖНО: В настоящее время мы поддерживаем только запросы CQL, возвращающие объекты типа «страница». Это означает, что все запросы CQL должны содержать «type=page» в качестве единственного фильтра типа. Также важно, чтобы не использовались фильтры для «lastModified», так как это вызовет проблемы с нашей логикой опроса коннектора. Мы по-прежнему будем получать все вложения и комментарии для страниц, возвращаемых запросом CQL. Любые фильтры «lastmodified» будут перезаписаны. Подробнее см. на странице https://developer.atlassian.com/server/confluence/advanced-searching-using-cql/.",
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
    description: "Настроить коннектор Jira",
    subtext: `Укажите любую ссылку на страницу Jira ниже и нажмите «Индексировать», чтобы индексировать. На основе предоставленной ссылки мы проиндексируем ВЕСЬ ПРОЕКТ, а не только указанную страницу. Например, если ввести https://onyx.atlassian.net/jira/software/projects/DAN/boards/1 и нажать кнопку «Индексировать», будет проиндексирован весь проект DAN Jira.`,
    values: [
      {
        type: "text",
        query: "Введите URL-адрес проекта Jira:",
        label: "URL-адрес проекта Jira",
        name: "jira_project_url",
        optional: false,
      },
      {
        type: "list",
        query:
          "Введите адреса электронной почты для добавления в черный список комментариев:",
        label: "Черный список камментариев",
        name: "comment_email_blacklist",
        description:
          "Это обычно полезно для игнорирования определенных ботов. Добавьте адреса электронной почты пользователей, комментарии которых НЕ должны индексироваться.",
        optional: true,
      },
    ],
    advanced_values: [],
  },
  redmine: {
    description: "Настроить коннектор Redmine",
    subtext: `Укажите любую ссылку на страницу Jira ниже и нажмите «Индексировать», чтобы индексировать. На основе предоставленной ссылки мы проиндексируем ВЕСЬ ПРОЕКТ, а не только указанную страницу. Например, если ввести https://onyx.atlassian.net/jira/software/projects/DAN/boards/1 и нажать кнопку «Индексировать», будет проиндексирован весь проект DAN Jira.`,
    values: [
      {
        type: "text",
        query: "Введите URL-адрес проекта Redmine:",
        label: "Название redmine",
        name: "redmine_project_url",
        optional: false,
      },
      {
        type: "list",
        query:
          "Введите адреса электронной почты для добавления в черный список комментариев:",
        label: "Черный список камментариев",
        name: "comment_email_blacklist",
        description:
          "Это обычно полезно для игнорирования определенных ботов. Добавьте адреса электронной почты пользователей, комментарии которых НЕ должны индексироваться.",
        optional: true,
      },
    ],
    advanced_values: [],
  },
  bitrix: {
    description: "Настроить bitrix коннектор",
    subtext: `Укажите любую ссылку на страницу Jira ниже и нажмите «Индексировать», чтобы индексировать. На основе предоставленной ссылки мы проиндексируем ВЕСЬ ПРОЕКТ, а не только указанную страницу. Например, если ввести https://onyx.atlassian.net/jira/software/projects/DAN/boards/1 и нажать кнопку «Индексировать», будет проиндексирован весь проект DAN Jira.`,
    values: [
      {
        type: "text",
        query: "Введите URL-адрес проекта bitrix:",
        label: "bitrix название",
        name: "bitrix_project_url",
        optional: false,
      },
      {
        type: "list",
        query:
          "Введите адреса электронной почты для добавления в черный список комментариев:",
        label: "Черный список камментариев",
        name: "comment_email_blacklist",
        description:
          "Это обычно полезно для игнорирования определенных ботов. Добавьте адреса электронной почты пользователей, комментарии которых НЕ должны индексироваться.",
        optional: true,
      },
    ],
    advanced_values: [],
  },
  file: {
    description: "Конфигурация файлового коннектора",
    values: [
      {
        type: "file",
        query: "Введите местоположение файлов:",
        label: "Расположение файлов",
        name: "file_locations",
        optional: false,
      },
    ],
    advanced_values: [],
  },
  notion: {
    description: "Настроить коннектор Notion",
    values: [
      {
        type: "text",
        query: "Введите идентификатор корневой страницы",
        label: "Корневой Page ID",
        name: "root_page_id",
        optional: true,
        description:
          "Если указано, будет индексировать только указанную страницу + все ее дочерние страницы. Если оставить пустым, будут индексироваться все страницы, к которым интеграции был предоставлен доступ.",
      },
    ],
    advanced_values: [],
  },
  github: {
    description: "Настроить коннектор GitHub",
    values: [
      {
        type: "text",
        query: "Введите владельца репозитория:",
        label: "Владелец репозитория",
        name: "repo_owner",
        optional: false,
      },
      {
        type: "text",
        query: "Введите название репозитория:",
        label: "Название репозитория",
        name: "repo_name",
        optional: false,
      },
      {
        type: "checkbox",
        query: "Включить pull requests?",
        label: "Включить pull requests?",
        description: "Индекс pull requests из этого репозитория",
        name: "include_prs",
        optional: true,
      },
      {
        type: "checkbox",
        query: "Включить issues?",
        label: "Включить Issues",
        name: "include_issues",
        description: "Индексировать issues из этого репозитория",
        optional: true,
      },
    ],
    advanced_values: [],
  },
  gitlab: {
    description: "Настроить коннектор GitLab",
    values: [
      {
        type: "text",
        query: "Введите владельца проекта:",
        label: "Владелец проекта",
        name: "project_owner",
        optional: false,
      },
      {
        type: "text",
        query: "Введите название проекта:",
        label: "Название проекта",
        name: "project_name",
        optional: false,
      },
      {
        type: "checkbox",
        query: "Включить merge requests?",
        label: "Включить MRs",
        name: "include_mrs",
        default: true,
        hidden: true,
      },
      {
        type: "checkbox",
        query: "Включить issues?",
        label: "Включить Issues",
        name: "include_issues",
        optional: true,
        hidden: true,
      },
    ],
    advanced_values: [],
  },
  gmail: {
    description: "Настроить коннектор Gmail",
    values: [],
    advanced_values: [],
  },
  sharepoint: {
    description: "Настроить коннектор SharePoint",
    values: [
      {
        type: "list",
        query: "Введите сайты SharePoint:",
        label: "Сайты",
        name: "sites",
        optional: true,
        description: `• Если сайты не указаны, будут проиндексированы все сайты в вашей организации (требуется разрешение Sites.Read.All).
        • Указание, например, «https://onyxai.sharepoint.com/sites/support» приведет к индексации только документов на этом сайте.
        • Указание, например, «https://onyxai.sharepoint.com/sites/support/subfolder» приведет к индексации только документов на этой папке.`,
      },
    ],
    advanced_values: [],
  },
  minio: {
    description: "Настроить коннектор S3",
    values: [
      {
        type: "text",
        query: "Введите название сегмента:",
        label: "Название сегмента",
        name: "bucket_name",
        optional: false,
      },
      {
        type: "text",
        query: "Введите префикс:",
        label: "Префикс",
        name: "prefix",
        optional: true,
      },
      {
        type: "text",
        label: "Тип сегмента",
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
    description: "Настроить коннектор Википедии",
    values: [
      {
        type: "text",
        query: "Введите код языка:",
        label: "Код языка",
        name: "language_code",
        optional: false,
        description: "Введите код языка Википедии (например, «en», «es»)",
      },
      {
        type: "list",
        query: "Введите категории для включения:",
        label: "Категории для индексации",
        name: "categories",
        description:
          "Укажите 0 или более названий категорий для индексации. Для большинства сайтов Википедии это страницы с названием в форме «Категория: XYZ», которые являются списками других страниц/категорий. Укажите только название категории, а не ее URL.",
        optional: true,
      },
      {
        type: "list",
        query: "Введите страницы для включения:",
        label: "Страницы",
        name: "pages",
        optional: true,
        description: "Укажите 0 или более названий страниц для индексации.",
      },
      {
        type: "number",
        query: "Введите глубину рекурсии:",
        label: "Глубина рекурсии",
        name: "recurse_depth",
        description:
          "При индексации категорий, имеющих подкатегории, это определит, как можно индексировать уровни. Укажите 0, чтобы индексировать только саму категорию (т. е. без рекурсии). Укажите -1 для неограниченной глубины рекурсии. Обратите внимание, что в некоторых редких случаях категория может содержать себя в своих зависимостях, что приведет к бесконечному циклу. Используйте -1, только если вы уверены, что этого не произойдет.",
        optional: false,
      },
    ],
    advanced_values: [],
  },
  yandex: {
    description: "Настроить коннектор Yandex Mail",
    values: [],
    advanced_values: [],
  },
  mailru: {
    description: "Настроить коннектор Mailru",
    values: [],
    advanced_values: [],
  },
  postgresql: {
    description: "Настроить коннектор SharePoint",
    values: [
      {
        type: "text",
        query: "Введите схему:",
        label: "Схема",
        name: "schema",
        optional: true,
      },
      {
        type: "text",
        query: "Введите таблицу:",
        label: "Таблица",
        name: "table_name",
      },
      {
        type: "text",
        query: "Введите столбцы:",
        label: "Столбцы с текстом",
        name: "conten_columns",
        optional: true,
      },
      {
        type: "text",
        query: "Введите столбцы:",
        label: "Столбцы метаданных",
        name: "metadata_columns",
        optional: true,
      },
      {
        type: "text",
        query: "Введите запрос:",
        label: "SQL-запрос",
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
    access_type: Yup.string().required("Требуется тип доступа"),
    name: Yup.string().required("Требуется имя коннектора"),
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
          schema = schema.required(`Требуется ${field.label}`);
        }

        acc[field.name] = schema;
        return acc;
      },
      {} as Record<string, any>
    ),
    // These are advanced settings
    indexingStart: Yup.string().nullable(),
    pruneFreq: Yup.number().min(
      0,
      "Частота обрезки должна быть неотрицательной"
    ),
    refreshFreq: Yup.number().min(
      0,
      "Частота обновления должна быть неотрицательной"
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
