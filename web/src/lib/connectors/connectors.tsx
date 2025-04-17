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
    description: "Настройка Web connector",
    values: [
      {
        type: "text",
        query:
          "Введите URL веб-сайта для сканирования, например https://docs.onyx.app/:",
        label: "Базовый URL",
        name: "base_url",
        optional: false,
      },
      {
        type: "select",
        query: "Выберите тип web connector:",
        label: "Метод сканирования",
        name: "web_connector_type",
        options: [
          { name: "рекурсивный", value: "recursive" },
          { name: "одиночный", value: "single" },
          { name: "sitemap", value: "sitemap" },
        ],
      },
    ],
    advanced_values: [
      {
        type: "checkbox",
        query: "Прокрутить перед сканированием:",
        label: "Прокрутить перед сканированием",
        description:
          "Включите, если для загрузки нужного контента требуется прокрутка",
        name: "scroll_before_scraping",
        optional: true,
      },
    ],
    overrideDefaultFreq: 86400,
  },
  github: {
    description: "Настройка GitHub connector",
    values: [
      {
        type: "text",
        query: "Введите имя пользователя или организацию GitHub:",
        label: "Владелец репозитория",
        name: "repo_owner",
        optional: false,
      },
      {
        type: "tab",
        name: "github_mode",
        label: "Что мы будем индексировать из GitHub?",
        optional: true,
        tabs: [
          {
            value: "repo",
            label: "Конкретный репозиторий",
            fields: [
              {
                type: "text",
                query: "Введите имя репозитория(ев):",
                label: "Имя репозитория(ев)",
                name: "repositories",
                optional: false,
                description:
                  "Для нескольких репозиториев введите имена через запятую (например, repo1,repo2,repo3)",
              },
            ],
          },
          {
            value: "everything",
            label: "Все",
            fields: [
              {
                type: "string_tab",
                label: "Все",
                name: "everything",
                description:
                  "Этот connector проиндексирует все репозитории, доступные предоставленным учетным данным!",
              },
            ],
          },
        ],
      },
      {
        type: "checkbox",
        query: "Включить pull requests?",
        label: "Включить pull requests?",
        description: "Индексировать pull requests из репозиториев",
        name: "include_prs",
        optional: true,
      },
      {
        type: "checkbox",
        query: "Включить issues?",
        label: "Включить Issues?",
        name: "include_issues",
        description: "Индексировать issues из репозиториев",
        optional: true,
      },
    ],
    advanced_values: [],
  },
  gitlab: {
    description: "Настройка GitLab connector",
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
        query: "Введите имя проекта:",
        label: "Имя проекта",
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
  gitbook: {
    description: "Настройка GitBook connector",
    values: [
      {
        type: "text",
        query: "Введите ID пространства:",
        label: "ID пространства",
        name: "space_id",
        optional: false,
        description:
          "ID пространства GitBook для индексации. Это можно найти в URL страницы в пространстве. Например, если ваш URL выглядит как `https://app.gitbook.com/o/ccLx08XZ5wZ54LwdP9QU/s/8JkzVx8QCIGRrmxhGHU8/`, то ваш ID пространства — `8JkzVx8QCIGRrmxhGHU8`.",
      },
    ],
    advanced_values: [],
  },
  google_drive: {
    description: "Настройка Google Drive connector",
    values: [
      {
        type: "tab",
        name: "indexing_scope",
        label: "Как мы будем индексировать ваш Google Drive?",
        optional: true,
        tabs: [
          {
            value: "general",
            label: "Общее",
            fields: [
              {
                type: "checkbox",
                label: "Включить общие диски?",
                description: (currentCredential) => {
                  return currentCredential?.credential_json?.google_tokens
                    ? "Это позволит SmartSearch индексировать все на общих дисках, к которым у вас есть доступ."
                    : "Это позволит SmartSearch индексировать все на общих дисках вашей организации.";
                },
                name: "include_shared_drives",
                default: false,
              },
              {
                type: "checkbox",
                label: (currentCredential) => {
                  return currentCredential?.credential_json?.google_tokens
                    ? "Включить Мой диск?"
                    : "Включить Мой диск для всех?";
                },
                description: (currentCredential) => {
                  return currentCredential?.credential_json?.google_tokens
                    ? "Это позволит SmartSearch индексировать все на вашем Моем диске."
                    : "Это позволит SmartSearch индексировать все на Моем диске каждого.";
                },
                name: "include_my_drives",
                default: false,
              },
              {
                type: "checkbox",
                description:
                  "Это позволит SmartSearch индексировать все файлы, доступные вам.",
                label: "Включить все файлы, доступные вам?",
                name: "include_files_shared_with_me",
                visibleCondition: (values, currentCredential) =>
                  currentCredential?.credential_json?.google_tokens,
                default: false,
              },
            ],
          },
          {
            value: "specific",
            label: "Конкретное",
            fields: [
              {
                type: "text",
                description: (currentCredential) => {
                  return currentCredential?.credential_json?.google_tokens
                    ? "Введите через запятую URL общих дисков, которые вы хотите индексировать. Вы должны иметь доступ к этим дискам."
                    : "Введите через запятую URL общих дисков, которые вы хотите индексировать.";
                },
                label: "URL общих дисков",
                name: "shared_drive_urls",
                default: "",
                isTextArea: true,
              },
              {
                type: "text",
                description:
                  "Введите через запятую URL папок, которые вы хотите индексировать. Файлы, расположенные в этих папках (и всех вложенных папках), будут проиндексированы.",
                label: "URL папок",
                name: "shared_folder_urls",
                default: "",
                isTextArea: true,
              },
              {
                type: "text",
                description:
                  "Введите через запятую email пользователей, чьи Мой диск вы хотите индексировать.",
                label: "Email Мой диск",
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
    description: "Настройка Gmail connector",
    values: [],
    advanced_values: [],
  },
  bookstack: {
    description: "Настройка Bookstack connector",
    values: [],
    advanced_values: [],
  },
  confluence: {
    description: "Настройка Confluence connector",
    initialConnectorName: "cloud_name",
    values: [
      {
        type: "checkbox",
        query: "Это экземпляр Confluence Cloud?",
        label: "Это Cloud",
        name: "is_cloud",
        optional: false,
        default: true,
        description:
          "Отметьте, если это экземпляр Confluence Cloud, снимите для Confluence Server/Data Center",
        disabled: (currentCredential) => {
          if (currentCredential?.credential_json?.confluence_refresh_token) {
            return true;
          }
          return false;
        },
      },
      {
        type: "text",
        query: "Введите базовый URL вики:",
        label: "Базовый URL вики",
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
          "Базовый URL вашего экземпляра Confluence (например, https://your-domain.atlassian.net/wiki)",
      },
      {
        type: "tab",
        name: "indexing_scope",
        label: "Как мы будем индексировать ваш Confluence?",
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
                  "Этот connector проиндексирует все страницы, доступные предоставленным учетным данным!",
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
                query: "Введите ID страницы:",
                label: "ID страницы",
                name: "page_id",
                default: "",
                description:
                  "Конкретный ID страницы для индексации (например, `131368`)",
              },
              {
                type: "checkbox",
                query: "Индексировать страницы рекурсивно?",
                label: "Индексировать рекурсивно",
                name: "index_recursively",
                description:
                  "Если включено, мы проиндексируем страницу, указанную по ID, а также все её дочерние страницы.",
                optional: false,
                default: true,
              },
            ],
          },
          {
            value: "cql",
            label: "CQL запрос",
            fields: [
              {
                type: "text",
                query: "Введите CQL запрос (опционально):",
                label: "CQL запрос",
                name: "cql_query",
                default: "",
                description:
                  "ВАЖНО: В настоящее время мы поддерживаем только CQL запросы, возвращающие объекты типа 'page'. Это означает, что все CQL запросы должны содержать 'type=page' как единственный фильтр типа. Также важно не использовать фильтры для 'lastModified', так как это вызовет проблемы с логикой опроса connector. Мы все равно получим все вложения и комментарии для страниц, возвращенных CQL запросом. Любые фильтры 'lastmodified' будут перезаписаны. Подробнее см. https://developer.atlassian.com/server/confluence/advanced-searching-using-cql/.",
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
    description: "Настройка Jira connector",
    subtext:
      "Настройте, какой контент Jira индексировать. Вы можете индексировать все или указать конкретный проект.",
    values: [
      {
        type: "text",
        query: "Введите базовый URL Jira:",
        label: "Базовый URL Jira",
        name: "jira_base_url",
        optional: false,
        description:
          "Базовый URL вашего экземпляра Jira (например, https://your-domain.atlassian.net)",
      },
      {
        type: "tab",
        name: "indexing_scope",
        label: "Как мы будем индексировать ваш Jira?",
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
                  "Этот connector проиндексирует все issues, доступные предоставленным учетным данным!",
              },
            ],
          },
          {
            value: "project",
            label: "Проект",
            fields: [
              {
                type: "text",
                query: "Введите ключ проекта:",
                label: "Ключ проекта",
                name: "project_key",
                description:
                  "Ключ конкретного проекта для индексации (например, 'PROJ').",
              },
            ],
          },
        ],
        defaultTab: "everything",
      },
      {
        type: "list",
        query: "Введите email адреса для черного списка комментариев:",
        label: "Черный список email для комментариев",
        name: "comment_email_blacklist",
        description:
          "Это полезно для игнорирования определенных ботов. Добавьте email пользователей, комментарии которых НЕ должны индексироваться.",
        optional: true,
      },
    ],
    advanced_values: [],
  },
  salesforce: {
    description: "Настройка Salesforce connector",
    values: [
      {
        type: "list",
        query: "Введите запрашиваемые объекты:",
        label: "Запрашиваемые объекты",
        name: "requested_objects",
        optional: true,
        description: `Укажите типы объектов Salesforce, которые вы хотите индексировать. Если не уверены, не указывайте объекты, и SmartSearch по умолчанию будет индексировать по 'Account'.

Подсказка: Используйте единственное число имени объекта (например, 'Opportunity' вместо 'Opportunities').`,
      },
    ],
    advanced_values: [],
  },
  sharepoint: {
    description: "Настройка коннектора SharePoint",
    values: [
      {
        type: "list",
        query: "Введите сайты SharePoint:",
        label: "Сайты",
        name: "sites",
        optional: true,
        description: `• Если сайты не указаны, будут проиндексированы все сайты в вашей организации (требуется разрешение Sites.Read.All).

• Указание, например, 'https://onyxai.sharepoint.com/sites/support' приведет к индексации только документов в этом сайте.

• Указание, например, 'https://onyxai.sharepoint.com/sites/support/subfolder' приведет к индексации только документов в этой папке.
`,
      },
    ],
    advanced_values: [],
  },
  teams: {
    description: "Настройка коннектора Teams",
    values: [
      {
        type: "list",
        query: "Введите Teams для включения:",
        label: "Teams",
        name: "teams",
        optional: true,
        description: `Укажите 0 или более Teams для индексации. Например, указание Team 'Support' для организации 'onyxai' приведет к индексации только сообщений в каналах, принадлежащих Team 'Support'. Если Teams не указаны, будут проиндексированы все Teams в вашей организации.`,
      },
    ],
    advanced_values: [],
  },
  discourse: {
    description: "Настройка коннектора Discourse",
    values: [
      {
        type: "text",
        query: "Введите базовый URL:",
        label: "Базовый URL",
        name: "base_url",
        optional: false,
      },
      {
        type: "list",
        query: "Введите категории для включения:",
        label: "Категории",
        name: "categories",
        optional: true,
      },
    ],
    advanced_values: [],
  },
  axero: {
    description: "Настройка коннектора Axero",
    values: [
      {
        type: "list",
        query: "Введите пространства для включения:",
        label: "Пространства",
        name: "spaces",
        optional: true,
        description:
          "Укажите ноль или более пространств для индексации (по ID пространств). Если ID пространств не указаны, будут проиндексированы все пространства.",
      },
    ],
    advanced_values: [],
    overrideDefaultFreq: 60 * 60 * 24,
  },
  productboard: {
    description: "Настройка коннектора Productboard",
    values: [],
    advanced_values: [],
  },
  slack: {
    description: "Настройка коннектора Slack",
    values: [],
    advanced_values: [
      {
        type: "list",
        query: "Введите каналы для включения:",
        label: "Каналы",
        name: "channels",
        description: `Укажите 0 или более каналов для индексации. Например, указание канала "support" приведет к индексации всего контента в канале "#support". Если каналы не указаны, будут проиндексированы все каналы в вашем рабочем пространстве.`,
        optional: true,
        transform: (values) => values.map((value) => value.toLowerCase()),
      },
      {
        type: "checkbox",
        query: "Включить регулярные выражения для каналов?",
        label: "Включить регулярные выражения для каналов",
        name: "channel_regex_enabled",
        description: `Если включено, "каналы", указанные выше, будут рассматриваться как регулярные выражения. Сообщения канала будут включены коннектором, если имя канала полностью соответствует любому из указанных регулярных выражений.
Например, указание .*-support.* в качестве "канала" приведет к включению любых каналов с "-support" в названии.`,
        optional: true,
      },
    ],
  },
  slab: {
    description: "Настройка коннектора Slab",
    values: [
      {
        type: "text",
        query: "Введите базовый URL:",
        label: "Базовый URL",
        name: "base_url",
        optional: false,
        description: `Укажите базовый URL для вашей команды Slab. Это будет выглядеть примерно так: https://onyx.slab.com/`,
      },
    ],
    advanced_values: [],
  },
  guru: {
    description: "Настройка коннектора Guru",
    values: [],
    advanced_values: [],
  },
  gong: {
    description: "Настройка коннектора Gong",
    values: [
      {
        type: "list",
        query: "Введите рабочие пространства для включения:",
        label: "Рабочие пространства",
        name: "workspaces",
        optional: true,
        description:
          "Укажите 0 или более рабочих пространств для индексации. Укажите ID рабочего пространства или ТОЧНОЕ название рабочего пространства из Gong. Если рабочие пространства не указаны, будут проиндексированы транскрипты из всех рабочих пространств.",
      },
    ],
    advanced_values: [],
  },
  loopio: {
    description: "Настройка коннектора Loopio",
    values: [
      {
        type: "text",
        query: "Введите название стека Loopio",
        label: "Название стека Loopio",
        name: "loopio_stack_name",
        description:
          "Должно точно совпадать с названием в управлении библиотекой. Оставьте это поле пустым, если хотите проиндексировать все стеки.",
        optional: true,
      },
    ],
    advanced_values: [],
    overrideDefaultFreq: 60 * 60 * 24,
  },
  file: {
    description: "Настройка коннектора для файлов",
    values: [
      {
        type: "file",
        query: "Введите расположения файлов:",
        label: "Расположения файлов",
        name: "file_locations",
        optional: false,
      },
    ],
    advanced_values: [],
  },
  zulip: {
    description: "Настройка коннектора Zulip",
    values: [
      {
        type: "text",
        query: "Введите название области:",
        label: "Название области",
        name: "realm_name",
        optional: false,
      },
      {
        type: "text",
        query: "Введите URL области:",
        label: "URL области",
        name: "realm_url",
        optional: false,
      },
    ],
    advanced_values: [],
  },
  notion: {
    description: "Настройка коннектора Notion",
    values: [
      {
        type: "text",
        query: "Введите ID корневой страницы:",
        label: "ID корневой страницы",
        name: "root_page_id",
        optional: true,
        description:
          "Если указано, будет проиндексирована только указанная страница и все её дочерние страницы. Если оставлено пустым, будут проиндексированы все страницы, к которым интеграция имеет доступ.",
      },
    ],
    advanced_values: [],
  },
  hubspot: {
    description: "Настройка коннектора HubSpot",
    values: [],
    advanced_values: [],
  },
  document360: {
    description: "Настройка коннектора Document360",
    values: [
      {
        type: "text",
        query: "Введите рабочее пространство:",
        label: "Рабочее пространство",
        name: "workspace",
        optional: false,
      },
      {
        type: "list",
        query: "Введите категории для включения:",
        label: "Категории",
        name: "categories",
        optional: true,
        description:
          "Укажите 0 или более категорий для индексации. Например, указание категории 'Помощь' приведет к индексации всего контента в категории 'Помощь'. Если категории не указаны, будут проиндексированы все категории в вашем рабочем пространстве.",
      },
    ],
    advanced_values: [],
  },
  clickup: {
    description: "Настройка коннектора ClickUp",
    values: [
      {
        type: "select",
        query: "Выберите тип коннектора:",
        label: "Тип коннектора",
        name: "connector_type",
        optional: false,
        options: [
          { name: "список", value: "list" },
          { name: "папка", value: "folder" },
          { name: "пространство", value: "space" },
          { name: "рабочее пространство", value: "workspace" },
        ],
      },
      {
        type: "list",
        query: "Введите ID коннекторов:",
        label: "ID коннекторов",
        name: "connector_ids",
        description: "Укажите 0 или более ID для индексации.",
        optional: true,
      },
      {
        type: "checkbox",
        query: "Получать комментарии к задачам?",
        label: "Получать комментарии к задачам",
        name: "retrieve_task_comments",
        description:
          "Если отмечено, все комментарии для каждой задачи также будут получены и проиндексированы.",
        optional: false,
      },
    ],
    advanced_values: [],
  },
  google_sites: {
    description: "Настройка коннектора Google Sites",
    values: [
      {
        type: "file",
        query: "Введите путь к zip-файлу:",
        label: "Расположение файлов",
        name: "file_locations",
        optional: false,
        description: "Загрузите zip-файл, содержащий HTML вашего сайта Google.",
      },
      {
        type: "text",
        query: "Введите базовый URL:",
        label: "Базовый URL",
        name: "base_url",
        optional: false,
      },
    ],
    advanced_values: [],
  },
  zendesk: {
    description: "Настройка коннектора Zendesk",
    values: [
      {
        type: "select",
        query: "Выберите тип контента для индексации:",
        label: "Тип контента",
        name: "content_type",
        optional: false,
        options: [
          { name: "статьи", value: "articles" },
          { name: "тикеты", value: "tickets" },
        ],
        default: "articles",
      },
    ],
    advanced_values: [],
  },
  linear: {
    description: "Настройка коннектора Linear",
    values: [],
    advanced_values: [],
  },
  dropbox: {
    description: "Настройка коннектора Dropbox",
    values: [],
    advanced_values: [],
  },
  s3: {
    description: "Настройка коннектора S3",
    values: [
      {
        type: "text",
        query: "Введите название бакета:",
        label: "Название бакета",
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
        label: "Тип бакета",
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
    description: "Настройка коннектора R2",
    values: [
      {
        type: "text",
        query: "Введите название бакета:",
        label: "Название бакета",
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
        label: "Тип бакета",
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
    description: "Настройка коннектора Google Cloud Storage",
    values: [
      {
        type: "text",
        query: "Введите название бакета:",
        label: "Название бакета",
        name: "bucket_name",
        optional: false,
        description:
          "Название бакета GCS для индексации, например, my-gcs-bucket",
      },
      {
        type: "text",
        query: "Введите префикс:",
        label: "Префикс пути",
        name: "prefix",
        optional: true,
      },
      {
        type: "text",
        label: "Тип бакета",
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
    description: "Настройка коннектора OCI Storage",
    values: [
      {
        type: "text",
        query: "Введите название бакета:",
        label: "Название бакета",
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
        label: "Тип бакета",
        name: "bucket_type",
        optional: false,
        default: "oci_storage",
        hidden: true,
      },
    ],
    advanced_values: [],
  },
  wikipedia: {
    description: "Настройка коннектора Wikipedia",
    values: [
      {
        type: "text",
        query: "Введите код языка:",
        label: "Код языка",
        name: "language_code",
        optional: false,
        description:
          "Введите действительный код языка Wikipedia (например, 'en', 'es')",
      },
      {
        type: "list",
        query: "Введите категории для включения:",
        label: "Категории для индексации",
        name: "categories",
        description:
          "Укажите 0 или более названий категорий для индексации. Для большинства сайтов Wikipedia это страницы с названием вида 'Категория: XYZ', которые являются списками других страниц/категорий. Указывайте только название категории, а не её URL.",
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
          "При индексации категорий, которые имеют подкатегории, это определит, сколько уровней индексировать. Укажите 0, чтобы индексировать только саму категорию (без рекурсии). Укажите -1 для неограниченной глубины рекурсии. Обратите внимание, что в редких случаях категория может содержать себя в своих зависимостях, что вызовет бесконечный цикл. Используйте -1 только если уверены, что этого не произойдет.",
        optional: false,
      },
    ],
    advanced_values: [],
  },
  xenforo: {
    description: "Настройка коннектора Xenforo",
    values: [
      {
        type: "text",
        query: "Введите URL форума или темы:",
        label: "URL",
        name: "base_url",
        optional: false,
        description:
          "URL форума XenForo v2.2 для индексации. Может быть доска или тема.",
      },
    ],
    advanced_values: [],
  },
  asana: {
    description: "Настройка коннектора Asana",
    values: [
      {
        type: "text",
        query: "Введите ID вашего рабочего пространства Asana:",
        label: "ID рабочего пространства",
        name: "asana_workspace_id",
        optional: false,
        description:
          "ID рабочего пространства Asana для индексации. Вы можете найти его на https://app.asana.com/api/1.0/workspaces. Это число, которое выглядит как 1234567890123456.",
      },
      {
        type: "text",
        query: "Введите ID проектов для индексации (необязательно):",
        label: "ID проектов",
        name: "asana_project_ids",
        description:
          "ID конкретных проектов Asana для индексации, разделенные запятыми. Оставьте пустым, чтобы индексировать все проекты в рабочем пространстве. Пример: 1234567890123456,2345678901234567",
        optional: true,
      },
      {
        type: "text",
        query: "Введите ID команды (необязательно):",
        label: "ID команды",
        name: "asana_team_id",
        optional: true,
        description:
          "ID команды для доступа к задачам, видимым команде. Это позволяет индексировать задачи, видимые команде, в дополнение к публичным задачам. Оставьте пустым, если не хотите использовать эту функцию.",
      },
    ],
    advanced_values: [],
  },
  mediawiki: {
    description: "Настройка коннектора MediaWiki",
    values: [
      {
        type: "text",
        query: "Введите код языка:",
        label: "Код языка",
        name: "language_code",
        optional: false,
        description:
          "Введите действительный код языка MediaWiki (например, 'en', 'es')",
      },
      {
        type: "text",
        query: "Введите URL сайта MediaWiki:",
        label: "URL сайта MediaWiki",
        name: "hostname",
        optional: false,
      },
      {
        type: "list",
        query: "Введите категории для включения:",
        label: "Категории для индексации",
        name: "categories",
        description:
          "Укажите 0 или более названий категорий для индексации. Для большинства сайтов MediaWiki это страницы с названием вида 'Категория: XYZ', которые являются списками других страниц/категорий. Указывайте только название категории, а не её URL.",
        optional: true,
      },
      {
        type: "list",
        query: "Введите страницы для включения:",
        label: "Страницы",
        name: "pages",
        optional: true,
        description:
          "Укажите 0 или более названий страниц для индексации. Указывайте только название страницы, а не её URL.",
      },
      {
        type: "number",
        query: "Введите глубину рекурсии:",
        label: "Глубина рекурсии",
        name: "recurse_depth",
        description:
          "При индексации категорий, которые имеют подкатегории, это определит, сколько уровней индексировать. Укажите 0, чтобы индексировать только саму категорию (без рекурсии). Укажите -1 для неограниченной глубины рекурсии. Обратите внимание, что в редких случаях категория может содержать себя в своих зависимостях, что вызовет бесконечный цикл. Используйте -1 только если уверены, что этого не произойдет.",
        optional: true,
      },
    ],
    advanced_values: [],
  },
  discord: {
    description: "Настройка коннектора Discord",
    values: [],
    advanced_values: [
      {
        type: "list",
        query: "Введите ID серверов для включения:",
        label: "ID серверов",
        name: "server_ids",
        description: `Укажите 0 или более ID серверов для включения. Только каналы внутри них будут использоваться для индексации.`,
        optional: true,
      },
      {
        type: "list",
        query: "Введите названия каналов для включения:",
        label: "Каналы",
        name: "channel_names",
        description: `Укажите 0 или более каналов для индексации. Например, указание канала "поддержка" приведет к индексации всего контента в канале "#поддержка". Если каналы не указаны, будут проиндексированы все каналы, к которым бот имеет доступ.`,
        optional: true,
      },
      {
        type: "text",
        query: "Введите начальную дату:",
        label: "Начальная дата",
        name: "start_date",
        description: `Только сообщения после этой даты будут проиндексированы. Формат: ГГГГ-ММ-ДД`,
        optional: true,
      },
    ],
  },
  freshdesk: {
    description: "Настройка коннектора Freshdesk",
    values: [],
    advanced_values: [],
  },
  fireflies: {
    description: "Настройка коннектора Fireflies",
    values: [],
    advanced_values: [],
  },
  egnyte: {
    description: "Настройка коннектора Egnyte",
    values: [
      {
        type: "text",
        query: "Введите путь к папке для индексации:",
        label: "Путь к папке",
        name: "folder_path",
        optional: true,
        description:
          "Путь к папке для индексации (например, '/Shared/Documents'). Оставьте пустым, чтобы индексировать всё.",
      },
    ],
    advanced_values: [],
  },
  airtable: {
    description: "Настройка коннектора Airtable",
    values: [
      {
        type: "text",
        query: "Введите ID базы:",
        label: "ID базы",
        name: "base_id",
        optional: false,
        description: "ID базы Airtable для индексации.",
      },
      {
        type: "text",
        query: "Введите название таблицы или ID таблицы:",
        label: "Название таблицы или ID таблицы",
        name: "table_name_or_id",
        optional: false,
      },
      {
        type: "checkbox",
        label: "Считать все поля, кроме вложений, метаданными",
        name: "treat_all_non_attachment_fields_as_metadata",
        description:
          "Выберите это, если основной контент для индексации — это вложения, а все остальные столбцы являются метаданными для этих вложений.",
        optional: false,
      },
    ],
    advanced_values: [
      {
        type: "text",
        label: "ID представления",
        name: "view_id",
        optional: true,
        description:
          "Если вам нужно ссылаться на конкретное представление, укажите его ID, например, viwVUEJjWPd8XYjh8.",
      },
      {
        type: "text",
        label: "ID общего доступа",
        name: "share_id",
        optional: true,
        description:
          "Если вам нужно ссылаться на конкретный общий доступ, укажите его ID, например, shrkfjEzDmLaDtK83.",
      },
    ],
    overrideDefaultFreq: 60 * 60 * 24,
  },
  highspot: {
    description: "Настройка коннектора Highspot",
    values: [
      {
        type: "tab",
        name: "highspot_scope",
        label: "Что мы будем индексировать из Highspot?",
        optional: true,
        tabs: [
          {
            value: "spots",
            label: "Конкретные Spots",
            fields: [
              {
                type: "list",
                query: "Введите название Spot(ов):",
                label: "Название Spot(ов)",
                name: "spot_names",
                optional: false,
                description: "Для нескольких Spots вводите их по одному.",
              },
            ],
          },
          {
            value: "everything",
            label: "Всё",
            fields: [
              {
                type: "string_tab",
                label: "Всё",
                name: "everything",
                description:
                  "Этот коннектор проиндексирует все Spots, к которым есть доступ у предоставленных учетных данных!",
              },
            ],
          },
        ],
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
    access_type: Yup.string().required("Access Type is required"),
    name: Yup.string().required("Connector Name is required"),
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
