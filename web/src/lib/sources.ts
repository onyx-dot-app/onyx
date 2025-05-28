import {
  BookstackIcon,
  ConfluenceIcon,
  FileIcon,
  GithubIcon,
  GitlabIcon,
  GlobeIcon,
  GmailIcon,
  JiraIcon,
  NotionIcon,
  SharepointIcon,
  WikipediaIcon,
  S3Icon,
  BitrixIcon,
  MailruIcon,
  RedmineIcon,
  YandexIcon,
  PostgreSQLIcon,
} from "@/components/icons/icons";
import { ValidSources } from "./types";
import { SourceCategory, SourceMetadata } from "./search/interfaces";
import { Persona } from "@/app/admin/assistants/interfaces";

interface PartialSourceMetadata {
  icon: React.FC<{ size?: number; className?: string }>;
  displayName: string;
  category: SourceCategory;
  docs?: string;
  adminUrl?: string;
}

type SourceMap = { [K in ValidSources]: PartialSourceMetadata };

const SOURCE_METADATA_MAP: SourceMap = {
  web: {
    icon: GlobeIcon,
    displayName: "Web",
    category: SourceCategory.ImportedKnowledge,
  },
  file: {
    icon: FileIcon,
    displayName: "Файл",
    category: SourceCategory.ImportedKnowledge,
    adminUrl: "file",
  },
  confluence: {
    icon: ConfluenceIcon,
    displayName: "Confluence",
    category: SourceCategory.AppConnection,
  },
  jira: {
    icon: JiraIcon,
    displayName: "Jira",
    category: SourceCategory.AppConnection,
  },
  redmine: {
    icon: RedmineIcon,
    displayName: "Redmine",
    category: SourceCategory.AppConnection,
  },
  bitrix: {
    icon: BitrixIcon,
    displayName: "Bitrix",
    category: SourceCategory.AppConnection,
  },
  notion: {
    icon: NotionIcon,
    displayName: "Notion",
    category: SourceCategory.AppConnection,
  },
  bookstack: {
    icon: BookstackIcon,
    displayName: "BookStack",
    category: SourceCategory.AppConnection,
  },
  minio: {
    icon: S3Icon,
    displayName: "S3",
    category: SourceCategory.AppConnection,
    adminUrl: "minio",
  },
  github: {
    icon: GithubIcon,
    displayName: "Github",
    category: SourceCategory.AppConnection,
  },
  gitlab: {
    icon: GitlabIcon,
    displayName: "Gitlab",
    category: SourceCategory.AppConnection,
  },
  gmail: {
    icon: GmailIcon,
    displayName: "Gmail",
    category: SourceCategory.AppConnection,
  },
  sharepoint: {
    icon: SharepointIcon,
    displayName: "Sharepoint",
    category: SourceCategory.AppConnection,
  },
  wikipedia: {
    icon: WikipediaIcon,
    displayName: "Wikipedia",
    category: SourceCategory.AppConnection,
  },
  yandex: {
    icon: YandexIcon,
    displayName: "Yandex Mail",
    category: SourceCategory.AppConnection,
    adminUrl: "yandex",
  },
  mailru: {
    icon: MailruIcon,
    displayName: "Mail",
    category: SourceCategory.AppConnection,
    adminUrl: "mailru",
  },
  postgresql: {
    icon: PostgreSQLIcon,
    displayName: "PostgreSQL",
    category: SourceCategory.AppConnection,
    adminUrl: "postgres",
  },
};

function fillSourceMetadata(
  partialMetadata: PartialSourceMetadata,
  internalName: ValidSources
): SourceMetadata {
  return {
    internalName: internalName,
    ...partialMetadata,
    adminUrl: `/admin/connectors/${internalName}`,
  };
}

export function getSourceMetadata(sourceType: ValidSources): SourceMetadata {
  const response = fillSourceMetadata(
    SOURCE_METADATA_MAP[sourceType],
    sourceType
  );

  return response;
}

export function listSourceMetadata(): SourceMetadata[] {
  /* This gives back all the viewable / common sources, primarily for 
  display in the Add Connector page */
  const entries = Object.entries(SOURCE_METADATA_MAP)
    .filter(
      ([source, _]) =>
        source !== "not_applicable" &&
        source !== "ingestion_api" &&
        source !== "mock_connector"
    )
    .map(([source, metadata]) => {
      return fillSourceMetadata(metadata, source as ValidSources);
    });
  return entries;
}

export function getSourceDocLink(sourceType: ValidSources): string | null {
  return SOURCE_METADATA_MAP[sourceType].docs || null;
}

export const isValidSource = (sourceType: string) => {
  return Object.keys(SOURCE_METADATA_MAP).includes(sourceType);
};

export function getSourceDisplayName(sourceType: ValidSources): string | null {
  return getSourceMetadata(sourceType).displayName;
}

export function getSourceMetadataForSources(sources: ValidSources[]) {
  return sources.map((source) => getSourceMetadata(source));
}

export function getSourcesForPersona(persona: Persona): ValidSources[] {
  const personaSources: ValidSources[] = [];
  persona.document_sets.forEach((documentSet) => {
    documentSet.cc_pair_descriptors.forEach((ccPair) => {
      if (!personaSources.includes(ccPair.connector.source)) {
        personaSources.push(ccPair.connector.source);
      }
    });
  });
  return personaSources;
}

export async function fetchTitleFromUrl(url: string): Promise<string | null> {
  try {
    const response = await fetch(url, {
      method: "GET",
      // If the remote site has no CORS header, this may fail in the browser
      mode: "cors",
    });
    if (!response.ok) {
      // Non-200 response, treat as a failure
      return null;
    }
    const html = await response.text();
    const parser = new DOMParser();
    const doc = parser.parseFromString(html, "text/html");
    // If the site has <title>My Demo Page</title>, we retrieve "My Demo Page"
    const pageTitle = doc.querySelector("title")?.innerText.trim() ?? null;
    return pageTitle;
  } catch (error) {
    console.error("Error fetching page title:", error);
    return null;
  }
}
