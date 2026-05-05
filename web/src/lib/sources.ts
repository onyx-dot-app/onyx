import { R2Icon, S3Icon, GoogleStorageIcon } from "@/components/icons/icons";
import { ValidSources } from "@/lib/types";
import { SourceCategory, SourceMetadata } from "@/lib/search/interfaces";
import { Persona } from "@/app/admin/agents/interfaces";
import React from "react";
import { DOCS_ADMINS_PATH, DOCS_BASE_URL } from "@/lib/constants";
import { SvgFileText, SvgGlobe, SvgUploadCloud, SvgMail } from "@opal/icons";
import {
  SvgAirtable,
  SvgAsana,
  SvgAxero,
  SvgBitbucket,
  SvgBookstack,
  SvgClickup,
  SvgCoda,
  SvgConfluence,
  SvgDiscord,
  SvgDiscourse,
  SvgDocument360,
  SvgDropbox,
  SvgDrupal,
  SvgEgnyte,
  SvgFireflies,
  SvgFreshdesk,
  SvgGitbook,
  SvgGithub,
  SvgGitlab,
  SvgGmail,
  SvgGong,
  SvgGoogleDrive,
  SvgGoogleSites,
  SvgGuru,
  SvgHighspot,
  SvgHubspot,
  SvgJira,
  SvgLinear,
  SvgLoopio,
  SvgMediawiki,
  SvgNotion,
  SvgOracle,
  SvgOutline,
  SvgProductboard,
  SvgSalesforce,
  SvgSharepoint,
  SvgSlack,
  SvgSlab,
  SvgTeams,
  SvgTestrail,
  SvgWikipedia,
  SvgXenforo,
  SvgZendesk,
  SvgZulip,
} from "@opal/logos";

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
  // For connectors that are always available (don't need connection setup)
  // e.g., User Library (CraftFile) where users just upload files
  alwaysConnected?: boolean;
  // Custom description to show instead of status (e.g., "Manage your uploaded files")
  customDescription?: string;
}

type SourceMap = {
  [K in ValidSources | "federated_slack"]: PartialSourceMetadata;
};

const slackMetadata = {
  icon: SvgSlack,
  displayName: "Slack",
  category: SourceCategory.Messaging,
  isPopular: true,
  docs: `${DOCS_ADMINS_PATH}/connectors/official/slack`,
  oauthSupported: true,
  // Federated Slack is available as an option but not the default
  federated: true,
  federatedTooltip:
    "⚠️ WARNING: Federated Slack results in significantly greater latency and lower search quality.",
  baseSourceType: "slack",
};

export const SOURCE_METADATA_MAP: SourceMap = {
  // Knowledge Base & Wikis
  confluence: {
    icon: SvgConfluence,
    displayName: "Confluence",
    category: SourceCategory.Wiki,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/confluence`,
    oauthSupported: true,
    isPopular: true,
  },
  sharepoint: {
    icon: SvgSharepoint,
    displayName: "Sharepoint",
    category: SourceCategory.Wiki,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/sharepoint`,
    isPopular: true,
  },
  coda: {
    icon: SvgCoda,
    displayName: "Coda",
    category: SourceCategory.Wiki,
    docs: "https://docs.onyx.app/connectors/coda",
  },
  notion: {
    icon: SvgNotion,
    displayName: "Notion",
    category: SourceCategory.Wiki,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/notion`,
  },
  bookstack: {
    icon: SvgBookstack,
    displayName: "BookStack",
    category: SourceCategory.Wiki,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/bookstack`,
  },
  document360: {
    icon: SvgDocument360,
    displayName: "Document360",
    category: SourceCategory.Wiki,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/document360`,
  },
  discourse: {
    icon: SvgDiscourse,
    displayName: "Discourse",
    category: SourceCategory.Wiki,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/discourse`,
  },
  gitbook: {
    icon: SvgGitbook,
    displayName: "GitBook",
    category: SourceCategory.Wiki,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/gitbook`,
  },
  slab: {
    icon: SvgSlab,
    displayName: "Slab",
    category: SourceCategory.Wiki,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/slab`,
  },
  outline: {
    icon: SvgOutline,
    displayName: "Outline",
    category: SourceCategory.Wiki,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/outline`,
  },
  google_sites: {
    icon: SvgGoogleSites,
    displayName: "Google Sites",
    category: SourceCategory.Wiki,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/google_sites`,
  },
  guru: {
    icon: SvgGuru,
    displayName: "Guru",
    category: SourceCategory.Wiki,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/guru`,
  },
  mediawiki: {
    icon: SvgMediawiki,
    displayName: "MediaWiki",
    category: SourceCategory.Wiki,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/mediawiki`,
  },
  axero: {
    icon: SvgAxero,
    displayName: "Axero",
    category: SourceCategory.Wiki,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/axero`,
  },
  wikipedia: {
    icon: SvgWikipedia,
    displayName: "Wikipedia",
    category: SourceCategory.Wiki,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/wikipedia`,
  },

  // Cloud Storage
  google_drive: {
    icon: SvgGoogleDrive,
    displayName: "Google Drive",
    category: SourceCategory.Storage,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/google_drive/overview`,
    oauthSupported: true,
    isPopular: true,
  },
  dropbox: {
    icon: SvgDropbox,
    displayName: "Dropbox",
    category: SourceCategory.Storage,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/dropbox`,
  },
  s3: {
    icon: S3Icon,
    displayName: "S3",
    category: SourceCategory.Storage,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/s3`,
  },
  google_cloud_storage: {
    icon: GoogleStorageIcon,
    displayName: "Google Storage",
    category: SourceCategory.Storage,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/google_storage`,
  },
  egnyte: {
    icon: SvgEgnyte,
    displayName: "Egnyte",
    category: SourceCategory.Storage,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/egnyte`,
  },
  oci_storage: {
    icon: SvgOracle,
    displayName: "Oracle Storage",
    category: SourceCategory.Storage,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/oci_storage`,
  },
  r2: {
    icon: R2Icon,
    displayName: "R2",
    category: SourceCategory.Storage,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/r2`,
  },

  // Ticketing & Task Management
  jira: {
    icon: SvgJira,
    displayName: "Jira",
    category: SourceCategory.TicketingAndTaskManagement,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/jira`,
    isPopular: true,
  },
  zendesk: {
    icon: SvgZendesk,
    displayName: "Zendesk",
    category: SourceCategory.TicketingAndTaskManagement,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/zendesk`,
    isPopular: true,
  },
  airtable: {
    icon: SvgAirtable,
    displayName: "Airtable",
    category: SourceCategory.TicketingAndTaskManagement,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/airtable`,
  },
  linear: {
    icon: SvgLinear,
    displayName: "Linear",
    category: SourceCategory.TicketingAndTaskManagement,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/linear`,
  },
  freshdesk: {
    icon: SvgFreshdesk,
    displayName: "Freshdesk",
    category: SourceCategory.TicketingAndTaskManagement,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/freshdesk`,
  },
  asana: {
    icon: SvgAsana,
    displayName: "Asana",
    category: SourceCategory.TicketingAndTaskManagement,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/asana`,
  },
  clickup: {
    icon: SvgClickup,
    displayName: "Clickup",
    category: SourceCategory.TicketingAndTaskManagement,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/clickup`,
  },
  productboard: {
    icon: SvgProductboard,
    displayName: "Productboard",
    category: SourceCategory.TicketingAndTaskManagement,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/productboard`,
  },
  testrail: {
    icon: SvgTestrail,
    displayName: "TestRail",
    category: SourceCategory.TicketingAndTaskManagement,
  },

  // Messaging
  slack: slackMetadata,
  federated_slack: slackMetadata,
  teams: {
    icon: SvgTeams,
    displayName: "Teams",
    category: SourceCategory.Messaging,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/teams`,
  },
  gmail: {
    icon: SvgGmail,
    displayName: "Gmail",
    category: SourceCategory.Messaging,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/gmail/overview`,
  },
  drupal_wiki: {
    icon: SvgDrupal,
    displayName: "Drupal Wiki",
    category: SourceCategory.Wiki,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/drupal_wiki`,
  },
  imap: {
    icon: SvgMail,
    displayName: "Email",
    category: SourceCategory.Messaging,
  },
  discord: {
    icon: SvgDiscord,
    displayName: "Discord",
    category: SourceCategory.Messaging,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/discord`,
  },
  xenforo: {
    icon: SvgXenforo,
    displayName: "Xenforo",
    category: SourceCategory.Messaging,
  },
  zulip: {
    icon: SvgZulip,
    displayName: "Zulip",
    category: SourceCategory.Messaging,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/zulip`,
  },

  // Sales
  salesforce: {
    icon: SvgSalesforce,
    displayName: "Salesforce",
    category: SourceCategory.Sales,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/salesforce`,
    isPopular: true,
  },
  hubspot: {
    icon: SvgHubspot,
    displayName: "HubSpot",
    category: SourceCategory.Sales,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/hubspot`,
    isPopular: true,
  },
  gong: {
    icon: SvgGong,
    displayName: "Gong",
    category: SourceCategory.Sales,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/gong`,
    isPopular: true,
  },
  fireflies: {
    icon: SvgFireflies,
    displayName: "Fireflies",
    category: SourceCategory.Sales,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/fireflies`,
  },
  highspot: {
    icon: SvgHighspot,
    displayName: "Highspot",
    category: SourceCategory.Sales,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/highspot`,
  },
  loopio: {
    icon: SvgLoopio,
    displayName: "Loopio",
    category: SourceCategory.Sales,
  },

  // Code Repository
  github: {
    icon: SvgGithub,
    displayName: "Github",
    category: SourceCategory.CodeRepository,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/github`,
    isPopular: true,
  },
  gitlab: {
    icon: SvgGitlab,
    displayName: "Gitlab",
    category: SourceCategory.CodeRepository,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/gitlab`,
  },
  bitbucket: {
    icon: SvgBitbucket,
    displayName: "Bitbucket",
    category: SourceCategory.CodeRepository,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/bitbucket`,
  },

  // Others
  web: {
    icon: SvgGlobe,
    displayName: "Web",
    category: SourceCategory.Other,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/web`,
    isPopular: true,
  },
  file: {
    icon: SvgFileText,
    displayName: "File",
    category: SourceCategory.Other,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/file`,
    isPopular: true,
  },
  user_file: {
    icon: SvgUploadCloud,
    displayName: "Uploaded Files",
    category: SourceCategory.Other,
    docs: `${DOCS_BASE_URL}/overview/core_features/chat#projects`,
    isPopular: false, // Needs to be false to hide from the Add Connector page
  },

  // Other
  ingestion_api: {
    icon: SvgGlobe,
    displayName: "Ingestion",
    category: SourceCategory.Other,
  },

  // Craft-specific sources
  craft_file: {
    icon: SvgFileText,
    displayName: "Your Files",
    category: SourceCategory.Other,
    isPopular: false, // Hidden from standard Add Connector page
    alwaysConnected: true, // No setup required, just upload files
    customDescription: "Manage your uploaded files",
  },

  // Placeholder (non-null default)
  not_applicable: {
    icon: SvgGlobe,
    displayName: "Not Applicable",
    category: SourceCategory.Other,
  },
  mock_connector: {
    icon: SvgGlobe,
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
  const partialMetadata = SOURCE_METADATA_MAP[sourceType];

  // Fallback to not_applicable if sourceType not found in map
  if (!partialMetadata) {
    return fillSourceMetadata(
      SOURCE_METADATA_MAP[ValidSources.NotApplicable],
      ValidSources.NotApplicable
    );
  }

  return fillSourceMetadata(partialMetadata, sourceType);
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

export function isValidSource(sourceType: string): boolean {
  return Object.keys(SOURCE_METADATA_MAP).includes(sourceType);
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
    documentSet.cc_pair_summaries.forEach((ccPair) => {
      if (!personaSources.includes(ccPair.source)) {
        personaSources.push(ccPair.source);
      }
    });
  });
  return personaSources;
}
