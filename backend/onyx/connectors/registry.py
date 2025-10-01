"""Registry mapping for connector classes."""

from pydantic import BaseModel

from onyx.configs.constants import DocumentSource


class ConnectorMapping(BaseModel):
    module_path: str
    class_name: str


# Mapping of DocumentSource to connector details for lazy loading
CONNECTOR_CLASS_MAP = {
    DocumentSource.WEB: ConnectorMapping(
        module_path="onyx.connectors.web.connector",
        class_name="WebConnector",
    ),
    DocumentSource.FILE: ConnectorMapping(
        module_path="onyx.connectors.file.connector",
        class_name="LocalFileConnector",
    ),
    DocumentSource.SLACK: ConnectorMapping(
        module_path="onyx.connectors.slack.connector",
        class_name="SlackConnector",
    ),
    DocumentSource.GITHUB: ConnectorMapping(
        module_path="onyx.connectors.github.connector",
        class_name="GithubConnector",
    ),
    DocumentSource.GMAIL: ConnectorMapping(
        module_path="onyx.connectors.gmail.connector",
        class_name="GmailConnector",
    ),
    DocumentSource.GITLAB: ConnectorMapping(
        module_path="onyx.connectors.gitlab.connector",
        class_name="GitlabConnector",
    ),
    DocumentSource.GITBOOK: ConnectorMapping(
        module_path="onyx.connectors.gitbook.connector",
        class_name="GitbookConnector",
    ),
    DocumentSource.GOOGLE_DRIVE: ConnectorMapping(
        module_path="onyx.connectors.google_drive.connector",
        class_name="GoogleDriveConnector",
    ),
    DocumentSource.BOOKSTACK: ConnectorMapping(
        module_path="onyx.connectors.bookstack.connector",
        class_name="BookstackConnector",
    ),
    DocumentSource.OUTLINE: ConnectorMapping(
        module_path="onyx.connectors.outline.connector",
        class_name="OutlineConnector",
    ),
    DocumentSource.CONFLUENCE: ConnectorMapping(
        module_path="onyx.connectors.confluence.connector",
        class_name="ConfluenceConnector",
    ),
    DocumentSource.JIRA: ConnectorMapping(
        module_path="onyx.connectors.jira.connector",
        class_name="JiraConnector",
    ),
    DocumentSource.PRODUCTBOARD: ConnectorMapping(
        module_path="onyx.connectors.productboard.connector",
        class_name="ProductboardConnector",
    ),
    DocumentSource.SLAB: ConnectorMapping(
        module_path="onyx.connectors.slab.connector",
        class_name="SlabConnector",
    ),
    DocumentSource.NOTION: ConnectorMapping(
        module_path="onyx.connectors.notion.connector",
        class_name="NotionConnector",
    ),
    DocumentSource.ZULIP: ConnectorMapping(
        module_path="onyx.connectors.zulip.connector",
        class_name="ZulipConnector",
    ),
    DocumentSource.GURU: ConnectorMapping(
        module_path="onyx.connectors.guru.connector",
        class_name="GuruConnector",
    ),
    DocumentSource.LINEAR: ConnectorMapping(
        module_path="onyx.connectors.linear.connector",
        class_name="LinearConnector",
    ),
    DocumentSource.HUBSPOT: ConnectorMapping(
        module_path="onyx.connectors.hubspot.connector",
        class_name="HubSpotConnector",
    ),
    DocumentSource.DOCUMENT360: ConnectorMapping(
        module_path="onyx.connectors.document360.connector",
        class_name="Document360Connector",
    ),
    DocumentSource.GONG: ConnectorMapping(
        module_path="onyx.connectors.gong.connector",
        class_name="GongConnector",
    ),
    DocumentSource.GOOGLE_SITES: ConnectorMapping(
        module_path="onyx.connectors.google_site.connector",
        class_name="GoogleSitesConnector",
    ),
    DocumentSource.ZENDESK: ConnectorMapping(
        module_path="onyx.connectors.zendesk.connector",
        class_name="ZendeskConnector",
    ),
    DocumentSource.LOOPIO: ConnectorMapping(
        module_path="onyx.connectors.loopio.connector",
        class_name="LoopioConnector",
    ),
    DocumentSource.DROPBOX: ConnectorMapping(
        module_path="onyx.connectors.dropbox.connector",
        class_name="DropboxConnector",
    ),
    DocumentSource.SHAREPOINT: ConnectorMapping(
        module_path="onyx.connectors.sharepoint.connector",
        class_name="SharepointConnector",
    ),
    DocumentSource.TEAMS: ConnectorMapping(
        module_path="onyx.connectors.teams.connector",
        class_name="TeamsConnector",
    ),
    DocumentSource.SALESFORCE: ConnectorMapping(
        module_path="onyx.connectors.salesforce.connector",
        class_name="SalesforceConnector",
    ),
    DocumentSource.DISCOURSE: ConnectorMapping(
        module_path="onyx.connectors.discourse.connector",
        class_name="DiscourseConnector",
    ),
    DocumentSource.AXERO: ConnectorMapping(
        module_path="onyx.connectors.axero.connector",
        class_name="AxeroConnector",
    ),
    DocumentSource.CLICKUP: ConnectorMapping(
        module_path="onyx.connectors.clickup.connector",
        class_name="ClickupConnector",
    ),
    DocumentSource.MEDIAWIKI: ConnectorMapping(
        module_path="onyx.connectors.mediawiki.wiki",
        class_name="MediaWikiConnector",
    ),
    DocumentSource.WIKIPEDIA: ConnectorMapping(
        module_path="onyx.connectors.wikipedia.connector",
        class_name="WikipediaConnector",
    ),
    DocumentSource.ASANA: ConnectorMapping(
        module_path="onyx.connectors.asana.connector",
        class_name="AsanaConnector",
    ),
    DocumentSource.S3: ConnectorMapping(
        module_path="onyx.connectors.blob.connector",
        class_name="BlobStorageConnector",
    ),
    DocumentSource.R2: ConnectorMapping(
        module_path="onyx.connectors.blob.connector",
        class_name="BlobStorageConnector",
    ),
    DocumentSource.GOOGLE_CLOUD_STORAGE: ConnectorMapping(
        module_path="onyx.connectors.blob.connector",
        class_name="BlobStorageConnector",
    ),
    DocumentSource.OCI_STORAGE: ConnectorMapping(
        module_path="onyx.connectors.blob.connector",
        class_name="BlobStorageConnector",
    ),
    DocumentSource.XENFORO: ConnectorMapping(
        module_path="onyx.connectors.xenforo.connector",
        class_name="XenforoConnector",
    ),
    DocumentSource.DISCORD: ConnectorMapping(
        module_path="onyx.connectors.discord.connector",
        class_name="DiscordConnector",
    ),
    DocumentSource.FRESHDESK: ConnectorMapping(
        module_path="onyx.connectors.freshdesk.connector",
        class_name="FreshdeskConnector",
    ),
    DocumentSource.FIREFLIES: ConnectorMapping(
        module_path="onyx.connectors.fireflies.connector",
        class_name="FirefliesConnector",
    ),
    DocumentSource.EGNYTE: ConnectorMapping(
        module_path="onyx.connectors.egnyte.connector",
        class_name="EgnyteConnector",
    ),
    DocumentSource.AIRTABLE: ConnectorMapping(
        module_path="onyx.connectors.airtable.airtable_connector",
        class_name="AirtableConnector",
    ),
    DocumentSource.HIGHSPOT: ConnectorMapping(
        module_path="onyx.connectors.highspot.connector",
        class_name="HighspotConnector",
    ),
    DocumentSource.IMAP: ConnectorMapping(
        module_path="onyx.connectors.imap.connector",
        class_name="ImapConnector",
    ),
    DocumentSource.BITBUCKET: ConnectorMapping(
        module_path="onyx.connectors.bitbucket.connector",
        class_name="BitbucketConnector",
    ),
    # just for integration tests
    DocumentSource.MOCK_CONNECTOR: ConnectorMapping(
        module_path="onyx.connectors.mock_connector.connector",
        class_name="MockConnector",
    ),
}
