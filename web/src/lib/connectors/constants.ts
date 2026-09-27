import type { FC } from "react";
import { DOCS_ADMINS_PATH, DOCS_BASE_URL } from "@/lib/constants";
import { SourceCategory, ValidSources } from "@/lib/connectors/types/source";
import { SvgFileText, SvgGlobe, SvgUploadCloud, SvgMail } from "@opal/icons";
import {
  SvgAirtable,
  SvgAsana,
  SvgAWS,
  SvgAxero,
  SvgBitbucket,
  SvgBookStack,
  SvgBox,
  SvgBraintrust,
  SvgCanvas,
  SvgClickUp,
  SvgCloudflare,
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
  SvgGitBook,
  SvgGitHub,
  SvgGitLab,
  SvgGmail,
  SvgGong,
  SvgGoogleCloud,
  SvgGoogleDrive,
  SvgGoogleSites,
  SvgGuru,
  SvgHighspot,
  SvgHubSpot,
  SvgJira,
  SvgLinear,
  SvgLoopio,
  SvgLumApps,
  SvgYouTrack,
  SvgMediaWiki,
  SvgNotion,
  SvgOneDrive,
  SvgOracle,
  SvgOutline,
  SvgOutlook,
  SvgProductboard,
  SvgSalesforce,
  SvgSeafile,
  SvgSharePoint,
  SvgSlab,
  SvgSlack,
  SvgTeams,
  SvgTestRail,
  SvgWikipedia,
  SvgXenForo,
  SvgZendesk,
  SvgZoom,
  SvgZulip,
} from "@opal/logos";

/**
 * Message key, inside the `admin.addConnector` namespace, for each category
 * heading in the connector catalog. The enum values are identifiers shared
 * across the app, so the labels live in the catalog rather than the enum.
 */
export const SOURCE_CATEGORY_LABEL_KEYS = {
  [SourceCategory.Wiki]: "categories.wiki.label",
  [SourceCategory.Storage]: "categories.storage.label",
  [SourceCategory.TicketingAndTaskManagement]:
    "categories.ticketingAndTaskManagement.label",
  [SourceCategory.Messaging]: "categories.messaging.label",
  [SourceCategory.Meetings]: "categories.meetings.label",
  [SourceCategory.Sales]: "categories.sales.label",
  [SourceCategory.CodeRepository]: "categories.codeRepository.label",
  [SourceCategory.AiObservability]: "categories.aiObservability.label",
  [SourceCategory.Other]: "categories.other.label",
} as const satisfies Record<SourceCategory, string>;

/** The catalog sections, in display order. */
export const CATALOG_CATEGORIES = Object.values(SourceCategory);

/**
 * Message key, inside the `admin.addConnector` namespace, for the one-line
 * summary shown under each source in the connector catalog. Keyed by every
 * `ValidSources` member so a new source cannot ship without a summary.
 */
export const SOURCE_DESCRIPTION_KEYS = {
  [ValidSources.Web]: "sources.web.description",
  [ValidSources.GitHub]: "sources.github.description",
  [ValidSources.GitLab]: "sources.gitlab.description",
  [ValidSources.Slack]: "sources.slack.description",
  [ValidSources.GoogleDrive]: "sources.googleDrive.description",
  [ValidSources.Gmail]: "sources.gmail.description",
  [ValidSources.Bookstack]: "sources.bookstack.description",
  [ValidSources.Outline]: "sources.outline.description",
  [ValidSources.Confluence]: "sources.confluence.description",
  [ValidSources.Jira]: "sources.jira.description",
  [ValidSources.Productboard]: "sources.productboard.description",
  [ValidSources.Slab]: "sources.slab.description",
  [ValidSources.Coda]: "sources.coda.description",
  [ValidSources.Notion]: "sources.notion.description",
  [ValidSources.Guru]: "sources.guru.description",
  [ValidSources.Gong]: "sources.gong.description",
  [ValidSources.Zulip]: "sources.zulip.description",
  [ValidSources.Linear]: "sources.linear.description",
  [ValidSources.Hubspot]: "sources.hubspot.description",
  [ValidSources.Document360]: "sources.document360.description",
  [ValidSources.File]: "sources.file.description",
  [ValidSources.UserFile]: "sources.userFile.description",
  [ValidSources.GoogleSites]: "sources.googleSites.description",
  [ValidSources.Loopio]: "sources.loopio.description",
  [ValidSources.Box]: "sources.box.description",
  [ValidSources.Dropbox]: "sources.dropbox.description",
  [ValidSources.Discord]: "sources.discord.description",
  [ValidSources.Salesforce]: "sources.salesforce.description",
  [ValidSources.Sharepoint]: "sources.sharepoint.description",
  [ValidSources.Teams]: "sources.teams.description",
  [ValidSources.Outlook]: "sources.outlook.description",
  [ValidSources.Zendesk]: "sources.zendesk.description",
  [ValidSources.Discourse]: "sources.discourse.description",
  [ValidSources.Axero]: "sources.axero.description",
  [ValidSources.Clickup]: "sources.clickup.description",
  [ValidSources.Wikipedia]: "sources.wikipedia.description",
  [ValidSources.Mediawiki]: "sources.mediawiki.description",
  [ValidSources.Asana]: "sources.asana.description",
  [ValidSources.S3]: "sources.s3.description",
  [ValidSources.R2]: "sources.r2.description",
  [ValidSources.GoogleCloudStorage]: "sources.googleCloudStorage.description",
  [ValidSources.Xenforo]: "sources.xenforo.description",
  [ValidSources.OciStorage]: "sources.ociStorage.description",
  [ValidSources.NotApplicable]: "sources.notApplicable.description",
  [ValidSources.IngestionApi]: "sources.ingestionApi.description",
  [ValidSources.Freshdesk]: "sources.freshdesk.description",
  [ValidSources.Fireflies]: "sources.fireflies.description",
  [ValidSources.Egnyte]: "sources.egnyte.description",
  [ValidSources.Airtable]: "sources.airtable.description",
  [ValidSources.Gitbook]: "sources.gitbook.description",
  [ValidSources.Highspot]: "sources.highspot.description",
  [ValidSources.DrupalWiki]: "sources.drupalWiki.description",
  [ValidSources.Imap]: "sources.imap.description",
  [ValidSources.Bitbucket]: "sources.bitbucket.description",
  [ValidSources.TestRail]: "sources.testrail.description",
  [ValidSources.Braintrust]: "sources.braintrust.description",
  [ValidSources.Lumapps]: "sources.lumapps.description",
  [ValidSources.YouTrack]: "sources.youtrack.description",
  [ValidSources.Canvas]: "sources.canvas.description",
  [ValidSources.CraftFile]: "sources.craftFile.description",
  [ValidSources.FederatedSlack]: "sources.federatedSlack.description",
  [ValidSources.OneDrive]: "sources.onedrive.description",
  [ValidSources.Zoom]: "sources.zoom.description",
  [ValidSources.Seafile]: "sources.seafile.description",
} as const satisfies Record<ValidSources, string>;

// ---------------------------------------------------------------------------
// Source metadata
// ---------------------------------------------------------------------------

export interface PartialSourceMetadata {
  icon: FC<{ size?: number; className?: string }>;
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
  lumapps: {
    icon: SvgLumApps,
    displayName: "LumApps",
    category: SourceCategory.Wiki,
  },
  sharepoint: {
    icon: SvgSharePoint,
    displayName: "SharePoint",
    category: SourceCategory.Wiki,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/sharepoint`,
    isPopular: true,
  },
  coda: {
    icon: SvgCoda,
    displayName: "Coda",
    category: SourceCategory.Wiki,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/coda`,
  },
  notion: {
    icon: SvgNotion,
    displayName: "Notion",
    category: SourceCategory.Wiki,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/notion`,
  },
  bookstack: {
    icon: SvgBookStack,
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
    icon: SvgGitBook,
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
    icon: SvgMediaWiki,
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
  canvas: {
    icon: SvgCanvas,
    displayName: "Canvas",
    category: SourceCategory.Wiki,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/canvas`,
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
  onedrive: {
    icon: SvgOneDrive,
    displayName: "OneDrive",
    category: SourceCategory.Storage,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/onedrive`,
  },
  seafile: {
    icon: SvgSeafile,
    displayName: "Seafile",
    category: SourceCategory.Storage,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/seafile`,
  },
  box: {
    icon: SvgBox,
    displayName: "Box",
    category: SourceCategory.Storage,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/box`,
  },
  dropbox: {
    icon: SvgDropbox,
    displayName: "Dropbox",
    category: SourceCategory.Storage,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/dropbox`,
  },
  s3: {
    icon: SvgAWS,
    displayName: "Amazon S3",
    category: SourceCategory.Storage,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/s3`,
  },
  google_cloud_storage: {
    icon: SvgGoogleCloud,
    displayName: "Google Cloud Storage",
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
    icon: SvgCloudflare,
    displayName: "Cloudflare R2",
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
  youtrack: {
    icon: SvgYouTrack,
    displayName: "YouTrack",
    category: SourceCategory.TicketingAndTaskManagement,
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
    icon: SvgClickUp,
    displayName: "ClickUp",
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
    icon: SvgTestRail,
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
  outlook: {
    icon: SvgOutlook,
    displayName: "Outlook",
    category: SourceCategory.Messaging,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/outlook`,
  },
  zoom: {
    icon: SvgZoom,
    displayName: "Zoom",
    category: SourceCategory.Meetings,
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
    icon: SvgXenForo,
    displayName: "XenForo",
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
    icon: SvgHubSpot,
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
    category: SourceCategory.Meetings,
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
    icon: SvgGitHub,
    displayName: "GitHub",
    category: SourceCategory.CodeRepository,
    docs: `${DOCS_ADMINS_PATH}/connectors/official/github`,
    isPopular: true,
  },
  gitlab: {
    icon: SvgGitLab,
    displayName: "GitLab",
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
  braintrust: {
    icon: SvgBraintrust,
    displayName: "Braintrust",
    category: SourceCategory.AiObservability,
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
