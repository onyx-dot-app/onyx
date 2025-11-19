import {
  AxeroIcon,
  BookstackIcon,
  OutlineIcon,
  ClickupIcon,
  ConfluenceIcon,
  DiscourseIcon,
  Document360Icon,
  DropboxIcon,
  GithubIcon,
  GitlabIcon,
  BitbucketIcon,
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
  docs: "https://docs.onyx.app/admin/connectors/official/slack",
  oauthSupported: true,
  federated: true,
  federatedTooltip:
    "⚠️ WARNING: Due to Slack's rate limit and ToS changes, Slack is now federated. " +
    "This will result in significantly greater latency and lower search quality.",
  baseSourceType: "slack",
};

export const SOURCE_METADATA_MAP: SourceMap = {
  // Knowledge Base & Wikis
  confluence: {
    icon: ConfluenceIcon,
    displayName: "Confluence",
    category: SourceCategory.Wiki,
    docs: "https://docs.onyx.app/admin/connectors/official/confluence",
    oauthSupported: true,
    isPopular: true,
  },
  sharepoint: {
    icon: SharepointIcon,
    displayName: "Sharepoint",
    category: SourceCategory.Wiki,
    docs: "https://docs.onyx.app/admin/connectors/official/sharepoint",
    isPopular: true,
  },
  notion: {
    icon: NotionIcon,
    displayName: "Notion",
    category: SourceCategory.Wiki,
    docs: "https://docs.onyx.app/admin/connectors/official/notion",
  },
  bookstack: {
    icon: BookstackIcon,
    displayName: "BookStack",
    category: SourceCategory.Wiki,
    docs: "https://docs.onyx.app/admin/connectors/official/bookstack",
  },
  document360: {
    icon: Document360Icon,
    displayName: "Document360",
    category: SourceCategory.Wiki,
    docs: "https://docs.onyx.app/admin/connectors/official/document360",
  },
  discourse: {
    icon: DiscourseIcon,
    displayName: "Discourse",
    category: SourceCategory.Wiki,
    docs: "https://docs.onyx.app/admin/connectors/official/discourse",
  },
  gitbook: {
    icon: GitbookIcon,
    displayName: "GitBook",
    category: SourceCategory.Wiki,
    docs: "https://docs.onyx.app/admin/connectors/official/gitbook",
  },
  slab: {
    icon: SlabIcon,
    displayName: "Slab",
    category: SourceCategory.Wiki,
    docs: "https://docs.onyx.app/admin/connectors/official/slab",
  },
  outline: {
    icon: OutlineIcon,
    displayName: "Outline",
    category: SourceCategory.Wiki,
    docs: "https://docs.onyx.app/admin/connectors/official/outline",
  },
  google_sites: {
    icon: GoogleSitesIcon,
    displayName: "Google Sites",
    category: SourceCategory.Wiki,
    docs: "https://docs.onyx.app/admin/connectors/official/google_sites",
  },
  guru: {
    icon: GuruIcon,
    displayName: "Guru",
    category: SourceCategory.Wiki,
    docs: "https://docs.onyx.app/admin/connectors/official/guru",
  },
  mediawiki: {
    icon: MediaWikiIcon,
    displayName: "MediaWiki",
    category: SourceCategory.Wiki,
    docs: "https://docs.onyx.app/admin/connectors/official/mediawiki",
  },
  axero: {
    icon: AxeroIcon,
    displayName: "Axero",
    category: SourceCategory.Wiki,
    docs: "https://docs.onyx.app/admin/connectors/official/axero",
  },
  wikipedia: {
    icon: WikipediaIcon,
    displayName: "Wikipedia",
    category: SourceCategory.Wiki,
    docs: "https://docs.onyx.app/admin/connectors/official/wikipedia",
  },

  // Cloud Storage
  google_drive: {
    icon: GoogleDriveIcon,
    displayName: "Google Drive",
    category: SourceCategory.Storage,
    docs: "https://docs.onyx.app/admin/connectors/official/google_drive/overview",
    oauthSupported: true,
    isPopular: true,
  },
  dropbox: {
    icon: DropboxIcon,
    displayName: "Dropbox",
    category: SourceCategory.Storage,
    docs: "https://docs.onyx.app/admin/connectors/official/dropbox",
  },
  s3: {
    icon: S3Icon,
    displayName: "S3",
    category: SourceCategory.Storage,
    docs: "https://docs.onyx.app/admin/connectors/official/s3",
  },
  google_cloud_storage: {
    icon: GoogleStorageIcon,
    displayName: "Google Storage",
    category: SourceCategory.Storage,
    docs: "https://docs.onyx.app/admin/connectors/official/google_storage",
  },
  egnyte: {
    icon: EgnyteIcon,
    displayName: "Egnyte",
    category: SourceCategory.Storage,
    docs: "https://docs.onyx.app/admin/connectors/official/egnyte",
  },
  oci_storage: {
    icon: OCIStorageIcon,
    displayName: "Oracle Storage",
    category: SourceCategory.Storage,
    docs: "https://docs.onyx.app/admin/connectors/official/oci_storage",
  },
  r2: {
    icon: R2Icon,
    displayName: "R2",
    category: SourceCategory.Storage,
    docs: "https://docs.onyx.app/admin/connectors/official/r2",
  },

  // Ticketing & Task Management
  jira: {
    icon: JiraIcon,
    displayName: "Jira",
    category: SourceCategory.TicketingAndTaskManagement,
    docs: "https://docs.onyx.app/admin/connectors/official/jira",
    isPopular: true,
  },
  zendesk: {
    icon: ZendeskIcon,
    displayName: "Zendesk",
    category: SourceCategory.TicketingAndTaskManagement,
    docs: "https://docs.onyx.app/admin/connectors/official/zendesk",
    isPopular: true,
  },
  airtable: {
    icon: AirtableIcon,
    displayName: "Airtable",
    category: SourceCategory.TicketingAndTaskManagement,
    docs: "https://docs.onyx.app/admin/connectors/official/airtable",
  },
  linear: {
    icon: LinearIcon,
    displayName: "Linear",
    category: SourceCategory.TicketingAndTaskManagement,
    docs: "https://docs.onyx.app/admin/connectors/official/linear",
  },
  freshdesk: {
    icon: FreshdeskIcon,
    displayName: "Freshdesk",
    category: SourceCategory.TicketingAndTaskManagement,
    docs: "https://docs.onyx.app/admin/connectors/official/freshdesk",
  },
  asana: {
    icon: AsanaIcon,
    displayName: "Asana",
    category: SourceCategory.TicketingAndTaskManagement,
    docs: "https://docs.onyx.app/admin/connectors/official/asana",
  },
  clickup: {
    icon: ClickupIcon,
    displayName: "Clickup",
    category: SourceCategory.TicketingAndTaskManagement,
    docs: "https://docs.onyx.app/admin/connectors/official/clickup",
  },
  productboard: {
    icon: ProductboardIcon,
    displayName: "Productboard",
    category: SourceCategory.TicketingAndTaskManagement,
    docs: "https://docs.onyx.app/admin/connectors/official/productboard",
  },

  // Messaging
  slack: slackMetadata,
  federated_slack: slackMetadata,
  teams: {
    icon: TeamsIcon,
    displayName: "Teams",
    category: SourceCategory.Messaging,
    docs: "https://docs.onyx.app/admin/connectors/official/teams",
  },
  gmail: {
    icon: GmailIcon,
    displayName: "Gmail",
    category: SourceCategory.Messaging,
    docs: "https://docs.onyx.app/admin/connectors/official/gmail/overview",
  },
  imap: {
    icon: EmailIcon,
    displayName: "Email",
    category: SourceCategory.Messaging,
  },
  discord: {
    icon: ColorDiscordIcon,
    displayName: "Discord",
    category: SourceCategory.Messaging,
    docs: "https://docs.onyx.app/admin/connectors/official/discord",
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
    docs: "https://docs.onyx.app/admin/connectors/official/zulip",
  },

  // Sales
  salesforce: {
    icon: SalesforceIcon,
    displayName: "Salesforce",
    category: SourceCategory.Sales,
    docs: "https://docs.onyx.app/admin/connectors/official/salesforce",
    isPopular: true,
  },
  hubspot: {
    icon: HubSpotIcon,
    displayName: "HubSpot",
    category: SourceCategory.Sales,
    docs: "https://docs.onyx.app/admin/connectors/official/hubspot",
    isPopular: true,
  },
  gong: {
    icon: GongIcon,
    displayName: "Gong",
    category: SourceCategory.Sales,
    docs: "https://docs.onyx.app/admin/connectors/official/gong",
    isPopular: true,
  },
  fireflies: {
    icon: FirefliesIcon,
    displayName: "Fireflies",
    category: SourceCategory.Sales,
    docs: "https://docs.onyx.app/admin/connectors/official/fireflies",
  },
  highspot: {
    icon: HighspotIcon,
    displayName: "Highspot",
    category: SourceCategory.Sales,
    docs: "https://docs.onyx.app/admin/connectors/official/highspot",
  },
  loopio: {
    icon: LoopioIcon,
    displayName: "Loopio",
    category: SourceCategory.Sales,
  },

  // Code Repository
  github: {
    icon: GithubIcon,
    displayName: "Github",
    category: SourceCategory.CodeRepository,
    docs: "https://docs.onyx.app/admin/connectors/official/github",
    isPopular: true,
  },
  gitlab: {
    icon: GitlabIcon,
    displayName: "Gitlab",
    category: SourceCategory.CodeRepository,
    docs: "https://docs.onyx.app/admin/connectors/official/gitlab",
  },
  bitbucket: {
    icon: BitbucketIcon,
    displayName: "Bitbucket",
    category: SourceCategory.CodeRepository,
    docs: "https://docs.onyx.app/connectors/bitbucket",
  },

  // Others
  web: {
    icon: GlobeIcon2,
    displayName: "Web",
    category: SourceCategory.Other,
    docs: "https://docs.onyx.app/admin/connectors/official/web",
    isPopular: true,
  },
  file: {
    icon: FileIcon2,
    displayName: "File",
    category: SourceCategory.Other,
    docs: "https://docs.onyx.app/admin/connectors/official/file",
    isPopular: true,
  },
  user_file: {
    // TODO: write docs for projects and link them here
    icon: FileIcon2,
    displayName: "File",
    category: SourceCategory.Other,
    docs: "https://docs.onyx.app/admin/connectors/official/file",
    isPopular: false, // Needs to be false to hide from the Add Connector page
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
        source !== "federated_slack" &&
        // user_file is for internal use (projects), not the Add Connector page
        source !== "user_file"
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
