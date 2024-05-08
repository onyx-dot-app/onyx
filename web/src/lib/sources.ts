import {
  AxeroIcon,
  BookstackIcon,
  ConfluenceIcon,
  DiscourseIcon,
  Document360Icon,
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
  RequestTrackerIcon,
  SharepointIcon,
  SlabIcon,
  SlackIcon,
  ZendeskIcon,
  ZulipIcon,
} from "@/components/icons/icons";
import { ValidSources } from "./types";
import { SourceCategory, SourceMetadata } from "./search/interfaces";
import { Persona } from "@/app/admin/assistants/interfaces";

interface PartialSourceMetadata {
  icon: React.FC<{ size?: number; className?: string }>;
  displayName: string;
  category: SourceCategory;
}

type SourceMap = {
  [K in ValidSources]: PartialSourceMetadata;
};

const SOURCE_METADATA_MAP: SourceMap = {
  web: {
    icon: GlobeIcon,
    displayName: "Web",
    category: SourceCategory.ImportedKnowledge,
  },
  file: {
    icon: FileIcon,
    displayName: "File",
    category: SourceCategory.ImportedKnowledge,
  },
  slack: {
    icon: SlackIcon,
    displayName: "Slack",
    category: SourceCategory.AppConnection,
  },
  gmail: {
    icon: GmailIcon,
    displayName: "Gmail",
    category: SourceCategory.AppConnection,
  },
  google_drive: {
    icon: GoogleDriveIcon,
    displayName: "Google Drive",
    category: SourceCategory.AppConnection,
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
  notion: {
    icon: NotionIcon,
    displayName: "Notion",
    category: SourceCategory.AppConnection,
  },
  zendesk: {
    icon: ZendeskIcon,
    displayName: "Zendesk",
    category: SourceCategory.AppConnection,
  },
  gong: {
    icon: GongIcon,
    displayName: "Gong",
    category: SourceCategory.AppConnection,
  },
  linear: {
    icon: LinearIcon,
    displayName: "Linear",
    category: SourceCategory.AppConnection,
  },
  productboard: {
    icon: ProductboardIcon,
    displayName: "Productboard",
    category: SourceCategory.AppConnection,
  },
  slab: {
    icon: SlabIcon,
    displayName: "Slab",
    category: SourceCategory.AppConnection,
  },
  zulip: {
    icon: ZulipIcon,
    displayName: "Zulip",
    category: SourceCategory.AppConnection,
  },
  guru: {
    icon: GuruIcon,
    displayName: "Guru",
    category: SourceCategory.AppConnection,
  },
  hubspot: {
    icon: HubSpotIcon,
    displayName: "HubSpot",
    category: SourceCategory.AppConnection,
  },
  document360: {
    icon: Document360Icon,
    displayName: "Document360",
    category: SourceCategory.AppConnection,
  },
  bookstack: {
    icon: BookstackIcon,
    displayName: "BookStack",
    category: SourceCategory.AppConnection,
  },
  google_sites: {
    icon: GoogleSitesIcon,
    displayName: "Google Sites",
    category: SourceCategory.ImportedKnowledge,
  },
  loopio: {
    icon: LoopioIcon,
    displayName: "Loopio",
    category: SourceCategory.AppConnection,
  },
  sharepoint: {
    icon: SharepointIcon,
    displayName: "Sharepoint",
    category: SourceCategory.AppConnection,
  },
  discourse: {
    icon: DiscourseIcon,
    displayName: "Discourse",
    category: SourceCategory.AppConnection,
  },
  axero: {
    icon: AxeroIcon,
    displayName: "Axero",
    category: SourceCategory.AppConnection,
  },
  requesttracker: {
    icon: RequestTrackerIcon,
    displayName: "Request Tracker",
    category: SourceCategory.AppConnection,
  },
};

function fillSourceMetadata(
  partialMetadata: PartialSourceMetadata,
  internalName: ValidSources
): SourceMetadata {
  return {
    internalName: internalName,
    ...partialMetadata,
    adminUrl: `/admin/connectors/${partialMetadata.displayName
      .toLowerCase()
      .replaceAll(" ", "-")}`,
  };
}

export function getSourceMetadata(sourceType: ValidSources): SourceMetadata {
  return fillSourceMetadata(SOURCE_METADATA_MAP[sourceType], sourceType);
}

export function listSourceMetadata(): SourceMetadata[] {
  return Object.entries(SOURCE_METADATA_MAP).map(([source, metadata]) => {
    return fillSourceMetadata(metadata, source as ValidSources);
  });
}

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
