import {
  AxeroIcon,
  BookstackIcon,
  ClickupIcon,
  ConfluenceIcon,
  DiscourseIcon,
  Document360Icon,
  DropboxIcon,
  FileIcon,
  GithubIcon,
  GitlabIcon,
  GlobeIcon,
  GmailIcon,
  GongIcon,
  GoogleDriveIcon,
  GoogleSitesIcon,
  GuruIcon,
  HubSpotIcon,
  JiraIcon,
  LinearIcon,
  LoopioIcon,
  NotionIcon,
  ProductboardIcon,
  R2Icon,
  SalesforceIcon,
  SharepointIcon,
  TeamsIcon,
  SlabIcon,
  ZendeskIcon,
  ZulipIcon,
  MediaWikiIcon,
  WikipediaIcon,
  AsanaIcon,
  S3Icon,
  OCIStorageIcon,
  GoogleStorageIcon,
  ColorSlackIcon,
  XenforoIcon,
  ColorDiscordIcon,
  FreshdeskIcon,
  FirefliesIcon,
  EgnyteIcon,
  AirtableIcon,
  GlobeIcon2,
  FileIcon2,
  GitbookIcon,
} from "@/components/icons/icons";
import { ValidSources } from "./types";
import {
  OnyxDocument,
  SourceCategory,
  SourceMetadata,
} from "./search/interfaces";
import { Persona } from "@/app/admin/assistants/interfaces";

interface PartialSourceMetadata {
  icon: React.FC<{ size?: number; className?: string }>;
  displayName: string;
  category: SourceCategory;
  docs?: string;
}

type SourceMap = {
  [K in ValidSources]: PartialSourceMetadata;
};

export const SOURCE_METADATA_MAP: SourceMap = {
  web: {
    icon: GlobeIcon2,
    displayName: "Web",
    category: SourceCategory.Other,
    docs: "https://docs.onyx.app/connectors/web",
  },
  file: {
    icon: FileIcon2,
    displayName: "File",
    category: SourceCategory.Storage,
    docs: "https://docs.onyx.app/connectors/file",
  },
  slack: {
    icon: ColorSlackIcon,
    displayName: "Slack",
    category: SourceCategory.Messaging,
    docs: "https://docs.onyx.app/connectors/slack",
    oauthSupported: true,
  },
  discord: {
    icon: ColorDiscordIcon,
    displayName: "Discord",
    category: SourceCategory.Messaging,
    docs: "https://docs.onyx.app/connectors/discord",
  },
  gmail: {
    icon: GmailIcon,
    displayName: "Gmail",
    category: SourceCategory.Messaging,
    docs: "https://docs.onyx.app/connectors/gmail/overview",
  },
  google_drive: {
    icon: GoogleDriveIcon,
    displayName: "Google Drive",
    category: SourceCategory.Storage,
    docs: "https://docs.onyx.app/connectors/google_drive/overview",
    oauthSupported: true,
  },
  github: {
    icon: GithubIcon,
    displayName: "Github",
    category: SourceCategory.CodeRepository,
    docs: "https://docs.onyx.app/connectors/github",
  },
  gitlab: {
    icon: GitlabIcon,
    displayName: "Gitlab",
    category: SourceCategory.CodeRepository,
    docs: "https://docs.onyx.app/connectors/gitlab",
  },
  confluence: {
    icon: ConfluenceIcon,
    displayName: "Confluence",
    category: SourceCategory.Wiki,
    docs: "https://docs.onyx.app/connectors/confluence",
  },
  jira: {
    icon: JiraIcon,
    displayName: "Jira",
    category: SourceCategory.ProjectManagement,
    docs: "https://docs.onyx.app/connectors/jira",
  },
  notion: {
    icon: NotionIcon,
    displayName: "Notion",
    category: SourceCategory.Wiki,
    docs: "https://docs.onyx.app/connectors/notion",
  },
  zendesk: {
    icon: ZendeskIcon,
    displayName: "Zendesk",
    category: SourceCategory.CustomerSupport,
    docs: "https://docs.onyx.app/connectors/zendesk",
  },
  gong: {
    icon: GongIcon,
    displayName: "Gong",
    category: SourceCategory.Other,
    docs: "https://docs.onyx.app/connectors/gong",
  },
  linear: {
    icon: LinearIcon,
    displayName: "Linear",
    category: SourceCategory.ProjectManagement,
    docs: "https://docs.onyx.app/connectors/linear",
  },
  productboard: {
    icon: ProductboardIcon,
    displayName: "Productboard",
    category: SourceCategory.ProjectManagement,
    docs: "https://docs.onyx.app/connectors/productboard",
  },
  slab: {
    icon: SlabIcon,
    displayName: "Slab",
    category: SourceCategory.Wiki,
    docs: "https://docs.onyx.app/connectors/slab",
  },
  zulip: {
    icon: ZulipIcon,
    displayName: "Zulip",
    category: SourceCategory.Messaging,
    docs: "https://docs.onyx.app/connectors/zulip",
  },
  guru: {
    icon: GuruIcon,
    displayName: "Guru",
    category: SourceCategory.Wiki,
    docs: "https://docs.onyx.app/connectors/guru",
  },
  hubspot: {
    icon: HubSpotIcon,
    displayName: "HubSpot",
    category: SourceCategory.CustomerSupport,
    docs: "https://docs.onyx.app/connectors/hubspot",
  },
  document360: {
    icon: Document360Icon,
    displayName: "Document360",
    category: SourceCategory.Wiki,
    docs: "https://docs.onyx.app/connectors/document360",
  },
  bookstack: {
    icon: BookstackIcon,
    displayName: "BookStack",
    category: SourceCategory.Wiki,
    docs: "https://docs.onyx.app/connectors/bookstack",
  },
  google_sites: {
    icon: GoogleSitesIcon,
    displayName: "Google Sites",
    category: SourceCategory.Wiki,
    docs: "https://docs.onyx.app/connectors/google_sites",
  },
  loopio: {
    icon: LoopioIcon,
    displayName: "Loopio",
    category: SourceCategory.Other,
  },
  dropbox: {
    icon: DropboxIcon,
    displayName: "Dropbox",
    category: SourceCategory.Storage,
    docs: "https://docs.onyx.app/connectors/dropbox",
  },
  salesforce: {
    icon: SalesforceIcon,
    displayName: "Salesforce",
    category: SourceCategory.CustomerSupport,
    docs: "https://docs.onyx.app/connectors/salesforce",
  },
  sharepoint: {
    icon: SharepointIcon,
    displayName: "Sharepoint",
    category: SourceCategory.Storage,
    docs: "https://docs.onyx.app/connectors/sharepoint",
  },
  teams: {
    icon: TeamsIcon,
    displayName: "Teams",
    category: SourceCategory.Messaging,
    docs: "https://docs.onyx.app/connectors/teams",
  },
  discourse: {
    icon: DiscourseIcon,
    displayName: "Discourse",
    category: SourceCategory.Messaging,
    docs: "https://docs.onyx.app/connectors/discourse",
  },
  axero: {
    icon: AxeroIcon,
    displayName: "Axero",
    category: SourceCategory.Wiki,
    docs: "https://docs.onyx.app/connectors/axero",
  },
  wikipedia: {
    icon: WikipediaIcon,
    displayName: "Wikipedia",
    category: SourceCategory.Wiki,
    docs: "https://docs.onyx.app/connectors/wikipedia",
  },
  asana: {
    icon: AsanaIcon,
    displayName: "Asana",
    category: SourceCategory.ProjectManagement,
    docs: "https://docs.onyx.app/connectors/asana",
  },
  mediawiki: {
    icon: MediaWikiIcon,
    displayName: "MediaWiki",
    category: SourceCategory.Wiki,
    docs: "https://docs.onyx.app/connectors/mediawiki",
  },
  clickup: {
    icon: ClickupIcon,
    displayName: "Clickup",
    category: SourceCategory.ProjectManagement,
    docs: "https://docs.onyx.app/connectors/clickup",
  },
  s3: {
    icon: S3Icon,
    displayName: "S3",
    category: SourceCategory.Storage,
    docs: "https://docs.onyx.app/connectors/s3",
  },
  r2: {
    icon: R2Icon,
    displayName: "R2",
    category: SourceCategory.Storage,
    docs: "https://docs.onyx.app/connectors/r2",
  },
  oci_storage: {
    icon: OCIStorageIcon,
    displayName: "Oracle Storage",
    category: SourceCategory.Storage,
    docs: "https://docs.onyx.app/connectors/oci_storage",
  },
  google_cloud_storage: {
    icon: GoogleStorageIcon,
    displayName: "Google Storage",
    category: SourceCategory.Storage,
    docs: "https://docs.onyx.app/connectors/google_storage",
  },
  xenforo: {
    icon: XenforoIcon,
    displayName: "Xenforo",
    category: SourceCategory.Messaging,
  },
  ingestion_api: {
    icon: GlobeIcon,
    displayName: "Ingestion",
    category: SourceCategory.Other,
  },
  freshdesk: {
    icon: FreshdeskIcon,
    displayName: "Freshdesk",
    category: SourceCategory.CustomerSupport,
    docs: "https://docs.onyx.app/connectors/freshdesk",
  },
  fireflies: {
    icon: FirefliesIcon,
    displayName: "Fireflies",
    category: SourceCategory.Other,
    docs: "https://docs.onyx.app/connectors/fireflies",
  },
  egnyte: {
    icon: EgnyteIcon,
    displayName: "Egnyte",
    category: SourceCategory.Storage,
    docs: "https://docs.onyx.app/connectors/egnyte",
  },
  airtable: {
    icon: AirtableIcon,
    displayName: "Airtable",
    category: SourceCategory.Other,
    docs: "https://docs.onyx.app/connectors/airtable",
  },
  gitbook: {
    icon: GitbookIcon,
    displayName: "GitBook",
    category: SourceCategory.Wiki,
    docs: "https://docs.onyx.app/connectors/gitbook",
  },
  // currently used for the Internet Search tool docs, which is why
  // a globe is used
  not_applicable: {
    icon: GlobeIcon,
    displayName: "Not Applicable",
    category: SourceCategory.Other,
  },

  // Just so integration tests don't crash the UI
  mock_connector: {
    icon: GlobeIcon,
    displayName: "Mock Connector",
    category: SourceCategory.Other,
  },
} as SourceMap;

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
      ([source, _]) => source !== "not_applicable" && source != "ingestion_api"
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
