/**
 * The sources a connector can index, and the sets carved out of them.
 *
 * These live with the connectors library rather than in the shared types
 * grab-bag: everything here is about what a connector can point at, and
 * nothing outside the connector surface defines a source.
 */

export enum ValidSources {
  Web = "web",
  GitHub = "github",
  GitLab = "gitlab",
  Slack = "slack",
  GoogleDrive = "google_drive",
  Gmail = "gmail",
  Bookstack = "bookstack",
  Outline = "outline",
  Confluence = "confluence",
  Jira = "jira",
  Productboard = "productboard",
  Slab = "slab",
  Coda = "coda",
  Notion = "notion",
  Guru = "guru",
  Gong = "gong",
  Zulip = "zulip",
  Linear = "linear",
  Hubspot = "hubspot",
  Document360 = "document360",
  File = "file",
  UserFile = "user_file",
  GoogleSites = "google_sites",
  Loopio = "loopio",
  Box = "box",
  Dropbox = "dropbox",
  Discord = "discord",
  Salesforce = "salesforce",
  Sharepoint = "sharepoint",
  OneDrive = "onedrive",
  Teams = "teams",
  Outlook = "outlook",
  Zendesk = "zendesk",
  Discourse = "discourse",
  Axero = "axero",
  Clickup = "clickup",
  Wikipedia = "wikipedia",
  Mediawiki = "mediawiki",
  Asana = "asana",
  S3 = "s3",
  R2 = "r2",
  GoogleCloudStorage = "google_cloud_storage",
  Xenforo = "xenforo",
  OciStorage = "oci_storage",
  NotApplicable = "not_applicable",
  IngestionApi = "ingestion_api",
  Freshdesk = "freshdesk",
  Fireflies = "fireflies",
  Egnyte = "egnyte",
  Airtable = "airtable",
  Gitbook = "gitbook",
  Highspot = "highspot",
  DrupalWiki = "drupal_wiki",
  Imap = "imap",
  Bitbucket = "bitbucket",
  TestRail = "testrail",
  Braintrust = "braintrust",
  Lumapps = "lumapps",
  Canvas = "canvas",
  Zoom = "zoom",

  // Craft-specific sources
  CraftFile = "craft_file",

  // Federated Connectors
  FederatedSlack = "federated_slack",
}

export const federatedSourceToRegularSource = (
  maybeFederatedSource: ValidSources
): ValidSources => {
  if (maybeFederatedSource === ValidSources.FederatedSlack) {
    return ValidSources.Slack;
  }
  return maybeFederatedSource;
};

export const validAutoSyncSources = [
  ValidSources.Confluence,
  ValidSources.Jira,
  ValidSources.GoogleDrive,
  ValidSources.Gmail,
  ValidSources.Slack,
  ValidSources.Salesforce,
  ValidSources.GitHub,
  ValidSources.Sharepoint,
  ValidSources.Teams,
  ValidSources.Outlook,
  ValidSources.Canvas,
  ValidSources.Box,
  ValidSources.OneDrive,
  ValidSources.Zoom,
  ValidSources.Hubspot,
] as const;

// Create a type from the array elements
export type ValidAutoSyncSource = (typeof validAutoSyncSources)[number];

export type ConfigurableSources = Exclude<
  ValidSources,
  | ValidSources.NotApplicable
  | ValidSources.IngestionApi
  | ValidSources.FederatedSlack // is part of ValiedSources.Slack
  | ValidSources.UserFile
  | ValidSources.CraftFile // User Library - managed through dedicated UI
>;

export const oauthSupportedSources: ConfigurableSources[] = [
  ValidSources.Slack,
  // NOTE: temporarily disabled until our GDrive App is approved
  // ValidSources.GoogleDrive,
  ValidSources.Confluence,
];

export type OAuthSupportedSource = (typeof oauthSupportedSources)[number];
