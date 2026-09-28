import { SourceCategory } from "@/lib/search/types";
import { ValidSources } from "@/lib/types";

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
  [ValidSources.Canvas]: "sources.canvas.description",
  [ValidSources.CraftFile]: "sources.craftFile.description",
  [ValidSources.FederatedSlack]: "sources.federatedSlack.description",
  [ValidSources.OneDrive]: "sources.onedrive.description",
} as const satisfies Record<ValidSources, string>;
