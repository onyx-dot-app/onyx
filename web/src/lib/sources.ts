import {
  AxeroIcon,
  BookstackIcon,
  ClickupIcon,
  ConfluenceIcon,
  DiscourseIcon,
  Document360Icon,
  DropboxIcon,
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
  HighspotIcon,
  EmailIcon,
} from "@/components/icons/icons";
import { ValidSources } from "./types";
import { SourceCategory, SourceMetadata } from "./search/interfaces";
import { Persona } from "@/app/admin/assistants/interfaces";

interface PartialSourceMetadata {
  icon: React.FC<{ size?: number; className?: string }>;
  displayName: string;
  category: SourceCategory;
  isPopular?: boolean;
  docs?: string;
  oauthSupported?: boolean;
  federated?: boolean;
  federatedTooltip?: string;
  // federated connectors store the base source type if it's a source
  // that has both indexed connectors and federated connectors
  baseSourceType?: ValidSources;
}

type SourceMap = {
  [K in ValidSources | "federated_slack"]: PartialSourceMetadata;
};

const slackMetadata = {
  icon: ColorSlackIcon,
  displayName: "Slack",
  category: SourceCategory.Messaging,
  isPopular: true,
  docs: "https://docs.onyx.app/connectors/slack",
  oauthSupported: true,
  federated: true,
  federatedTooltip:
    "⚠️ WARNING: Due to Slack's rate limit and ToS changes, Slack is now federated. " +
    "This will result in significantly greater latency and lower search quality.",
  baseSourceType: "slack",
};

export const SOURCE_METADATA_MAP: SourceMap = {
  // Keep web and file at the top
  web: {
    icon: GlobeIcon2,
    displayName: "Web",
    category: SourceCategory.Other,
    docs: "https://docs.onyx.app/connectors/web",
    isPopular: true,
  },
  file: {
    icon: FileIcon2,
    displayName: "File",
    category: SourceCategory.Other,
    docs: "https://docs.onyx.app/connectors/file",
    isPopular: true,
  },

  // Cloud Storage
  dropbox: {
    icon: DropboxIcon,
    displayName: "Dropbox",
    category: SourceCategory.Storage,
    docs: "https://docs.onyx.app/connectors/dropbox",
  },
  egnyte: {
    icon: EgnyteIcon,
    displayName: "Egnyte",
    category: SourceCategory.Storage,
    docs: "https://docs.onyx.app/connectors/egnyte",
  },
  google_cloud_storage: {
    icon: GoogleStorageIcon,
    displayName: "Google Storage",
    category: SourceCategory.Storage,
    docs: "https://docs.onyx.app/connectors/google_storage",
  },
  google_drive: {
    icon: GoogleDriveIcon,
    displayName: "Google Drive",
    category: SourceCategory.Storage,
    docs: "https://docs.onyx.app/connectors/google_drive/overview",
    oauthSupported: true,
    isPopular: true,
  },
  oci_storage: {
    icon: OCIStorageIcon,
    displayName: "Oracle Storage",
    category: SourceCategory.Storage,
    docs: "https://docs.onyx.app/connectors/oci_storage",
  },
  r2: {
    icon: R2Icon,
    displayName: "R2",
    category: SourceCategory.Storage,
    docs: "https://docs.onyx.app/connectors/r2",
  },
  s3: {
    icon: S3Icon,
    displayName: "S3",
    category: SourceCategory.Storage,
    docs: "https://docs.onyx.app/connectors/s3",
  },
  sharepoint: {
    icon: SharepointIcon,
    displayName: "Sharepoint",
    category: SourceCategory.Storage,
    docs: "https://docs.onyx.app/connectors/sharepoint",
    isPopular: true,
  },

  // Code Repository
  github: {
    icon: GithubIcon,
    displayName: "Github",
    category: SourceCategory.CodeRepository,
    docs: "https://docs.onyx.app/connectors/github",
    isPopular: true,
  },
  gitlab: {
    icon: GitlabIcon,
    displayName: "Gitlab",
    category: SourceCategory.CodeRepository,
    docs: "https://docs.onyx.app/connectors/gitlab",
  },

  // Customer Support
  freshdesk: {
    icon: FreshdeskIcon,
    displayName: "Freshdesk",
    category: SourceCategory.CustomerSupport,
    docs: "https://docs.onyx.app/connectors/freshdesk",
  },
  zendesk: {
    icon: ZendeskIcon,
    displayName: "Zendesk",
    category: SourceCategory.CustomerSupport,
    docs: "https://docs.onyx.app/connectors/zendesk",
    isPopular: true,
  },

  // Knowledge Base & Wiki
  axero: {
    icon: AxeroIcon,
    displayName: "Axero",
    category: SourceCategory.Wiki,
    docs: "https://docs.onyx.app/connectors/axero",
  },
  bookstack: {
    icon: BookstackIcon,
    displayName: "BookStack",
    category: SourceCategory.Wiki,
    docs: "https://docs.onyx.app/connectors/bookstack",
  },
  confluence: {
    icon: ConfluenceIcon,
    displayName: "Confluence",
    category: SourceCategory.Wiki,
    docs: "https://docs.onyx.app/connectors/confluence",
    oauthSupported: true,
    isPopular: true,
  },
  document360: {
    icon: Document360Icon,
    displayName: "Document360",
    category: SourceCategory.Wiki,
    docs: "https://docs.onyx.app/connectors/document360",
  },
  gitbook: {
    icon: GitbookIcon,
    displayName: "GitBook",
    category: SourceCategory.Wiki,
    docs: "https://docs.onyx.app/connectors/gitbook",
  },
  google_sites: {
    icon: GoogleSitesIcon,
    displayName: "Google Sites",
    category: SourceCategory.Wiki,
    docs: "https://docs.onyx.app/connectors/google_sites",
  },
  guru: {
    icon: GuruIcon,
    displayName: "Guru",
    category: SourceCategory.Wiki,
    docs: "https://docs.onyx.app/connectors/guru",
  },
  highspot: {
    icon: HighspotIcon,
    displayName: "Highspot",
    category: SourceCategory.Wiki,
    docs: "https://docs.onyx.app/connectors/highspot",
  },
  mediawiki: {
    icon: MediaWikiIcon,
    displayName: "MediaWiki",
    category: SourceCategory.Wiki,
    docs: "https://docs.onyx.app/connectors/mediawiki",
  },
  notion: {
    icon: NotionIcon,
    displayName: "Notion",
    category: SourceCategory.Wiki,
    docs: "https://docs.onyx.app/connectors/notion",
  },
  slab: {
    icon: SlabIcon,
    displayName: "Slab",
    category: SourceCategory.Wiki,
    docs: "https://docs.onyx.app/connectors/slab",
  },
  wikipedia: {
    icon: WikipediaIcon,
    displayName: "Wikipedia",
    category: SourceCategory.Wiki,
    docs: "https://docs.onyx.app/connectors/wikipedia",
  },

  // Messaging
  discord: {
    icon: ColorDiscordIcon,
    displayName: "Discord",
    category: SourceCategory.Messaging,
    docs: "https://docs.onyx.app/connectors/discord",
  },
  discourse: {
    icon: DiscourseIcon,
    displayName: "Discourse",
    category: SourceCategory.Messaging,
    docs: "https://docs.onyx.app/connectors/discourse",
  },
  gmail: {
    icon: GmailIcon,
    displayName: "Gmail",
    category: SourceCategory.Messaging,
    docs: "https://docs.onyx.app/connectors/gmail/overview",
  },
  imap: {
    icon: EmailIcon,
    displayName: "Email",
    category: SourceCategory.Messaging,
  },
  slack: slackMetadata,
  federated_slack: slackMetadata,
  teams: {
    icon: TeamsIcon,
    displayName: "Teams",
    category: SourceCategory.Messaging,
    docs: "https://docs.onyx.app/connectors/teams",
  },
  xenforo: {
    icon: XenforoIcon,
    displayName: "Xenforo",
    category: SourceCategory.Messaging,
  },
  zulip: {
    icon: ZulipIcon,
    displayName: "Zulip",
    category: SourceCategory.Messaging,
    docs: "https://docs.onyx.app/connectors/zulip",
  },

  // Project Management
  airtable: {
    icon: AirtableIcon,
    displayName: "Airtable",
    category: SourceCategory.ProjectManagement,
    docs: "https://docs.onyx.app/connectors/airtable",
  },
  asana: {
    icon: AsanaIcon,
    displayName: "Asana",
    category: SourceCategory.ProjectManagement,
    docs: "https://docs.onyx.app/connectors/asana",
  },
  clickup: {
    icon: ClickupIcon,
    displayName: "Clickup",
    category: SourceCategory.ProjectManagement,
    docs: "https://docs.onyx.app/connectors/clickup",
  },
  jira: {
    icon: JiraIcon,
    displayName: "Jira",
    category: SourceCategory.ProjectManagement,
    docs: "https://docs.onyx.app/connectors/jira",
    isPopular: true,
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

  // Sales & Marketing
  fireflies: {
    icon: FirefliesIcon,
    displayName: "Fireflies",
    category: SourceCategory.SalesAndMarketing,
    docs: "https://docs.onyx.app/connectors/fireflies",
  },
  gong: {
    icon: GongIcon,
    displayName: "Gong",
    category: SourceCategory.SalesAndMarketing,
    docs: "https://docs.onyx.app/connectors/gong",
    isPopular: true,
  },
  hubspot: {
    icon: HubSpotIcon,
    displayName: "HubSpot",
    category: SourceCategory.SalesAndMarketing,
    docs: "https://docs.onyx.app/connectors/hubspot",
  },
  loopio: {
    icon: LoopioIcon,
    displayName: "Loopio",
    category: SourceCategory.SalesAndMarketing,
  },
  salesforce: {
    icon: SalesforceIcon,
    displayName: "Salesforce",
    category: SourceCategory.SalesAndMarketing,
    docs: "https://docs.onyx.app/connectors/salesforce",
    isPopular: true,
  },

  // Other
  ingestion_api: {
    icon: GlobeIcon,
    displayName: "Ingestion",
    category: SourceCategory.Other,
  },

  // Placeholder (non-null default)
  not_applicable: {
    icon: GlobeIcon,
    displayName: "Not Applicable",
    category: SourceCategory.Other,
  },
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
    internalName: partialMetadata.baseSourceType || internalName,
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
        source !== "mock_connector" &&
        // use the "regular" slack connector when listing
        source !== "federated_slack"
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
    documentSet.cc_pair_summaries.forEach((ccPair) => {
      if (!personaSources.includes(ccPair.source)) {
        personaSources.push(ccPair.source);
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
