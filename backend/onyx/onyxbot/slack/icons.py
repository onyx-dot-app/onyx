from collections.abc import Mapping

from onyx.configs.constants import DocumentSource

_PUBLIC_SOURCE_IMAGE_BASE_URL = "https://raw.githubusercontent.com/onyx-dot-app/onyx/main/web/public/slackbot-source-icons"
_DEFAULT_SOURCE_IMAGE_FILENAME = "File.png"

_SOURCE_IMAGE_FILENAMES: Mapping[DocumentSource, str] = {
    DocumentSource.INGESTION_API: _DEFAULT_SOURCE_IMAGE_FILENAME,
    DocumentSource.SLACK: "Slack.png",
    DocumentSource.WEB: "Web.png",
    DocumentSource.GOOGLE_DRIVE: "GoogleDrive.png",
    DocumentSource.GMAIL: "Gmail.png",
    DocumentSource.GITHUB: "Github.png",
    DocumentSource.GITBOOK: "Gitbook.png",
    DocumentSource.GITLAB: "Gitlab.png",
    DocumentSource.GURU: "Guru.png",
    DocumentSource.BOOKSTACK: "Bookstack.png",
    DocumentSource.OUTLINE: "Outline.png",
    DocumentSource.CONFLUENCE: "Confluence.png",
    DocumentSource.JIRA: "Jira.png",
    DocumentSource.SLAB: "Slab.png",
    DocumentSource.PRODUCTBOARD: "Productboard.png",
    DocumentSource.FILE: _DEFAULT_SOURCE_IMAGE_FILENAME,
    DocumentSource.CODA: "Coda.png",
    DocumentSource.CANVAS: _DEFAULT_SOURCE_IMAGE_FILENAME,
    DocumentSource.NOTION: "Notion.png",
    DocumentSource.ZULIP: "Zulip.png",
    DocumentSource.LINEAR: "Linear.png",
    DocumentSource.HUBSPOT: "HubSpot.png",
    DocumentSource.DOCUMENT360: "Document360.png",
    DocumentSource.GONG: "Gong.png",
    DocumentSource.GOOGLE_SITES: "GoogleSites.png",
    DocumentSource.ZENDESK: "Zendesk.png",
    DocumentSource.LOOPIO: "Loopio.png",
    DocumentSource.DROPBOX: "Dropbox.png",
    DocumentSource.SHAREPOINT: "Sharepoint.png",
    DocumentSource.TEAMS: "Teams.png",
    DocumentSource.SALESFORCE: "Salesforce.png",
    DocumentSource.DISCOURSE: "Discourse.png",
    DocumentSource.AXERO: "Axero.png",
    DocumentSource.CLICKUP: "Clickup.png",
    DocumentSource.MEDIAWIKI: "MediaWiki.png",
    DocumentSource.WIKIPEDIA: "Wikipedia.png",
    DocumentSource.ASANA: "Asana.png",
    DocumentSource.S3: "S3.png",
    DocumentSource.R2: "R2.png",
    DocumentSource.GOOGLE_CLOUD_STORAGE: "GoogleCloudStorage.png",
    DocumentSource.OCI_STORAGE: "OCI.png",
    DocumentSource.XENFORO: "Xenforo.png",
    DocumentSource.NOT_APPLICABLE: _DEFAULT_SOURCE_IMAGE_FILENAME,
    DocumentSource.DISCORD: "Discord.png",
    DocumentSource.FRESHDESK: "Freshdesk.png",
    DocumentSource.FIREFLIES: "Fireflies.png",
    DocumentSource.EGNYTE: "Egnyte.png",
    DocumentSource.AIRTABLE: "Airtable.png",
    DocumentSource.HIGHSPOT: "Highspot.png",
    DocumentSource.DRUPAL_WIKI: "Drupal.png",
    DocumentSource.IMAP: "Mail.png",
    DocumentSource.BITBUCKET: "Bitbucket.png",
    DocumentSource.TESTRAIL: "Testrail.png",
    DocumentSource.BRAINTRUST: "Braintrust.png",
    DocumentSource.MOCK_CONNECTOR: _DEFAULT_SOURCE_IMAGE_FILENAME,
    DocumentSource.USER_FILE: _DEFAULT_SOURCE_IMAGE_FILENAME,
    DocumentSource.CRAFT_FILE: _DEFAULT_SOURCE_IMAGE_FILENAME,
}


def source_to_github_img_link(source: DocumentSource) -> str:
    filename = _SOURCE_IMAGE_FILENAMES[source]

    return f"{_PUBLIC_SOURCE_IMAGE_BASE_URL}/{filename}"
