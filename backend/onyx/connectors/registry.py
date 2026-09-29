"""Registry mapping for connector classes."""

from pydantic import BaseModel

from onyx.configs.constants import DocumentSource
from onyx.connectors.axero.config import AxeroConnectorConfig
from onyx.connectors.blob.config import BlobStorageConnectorConfig
from onyx.connectors.bookstack.config import BookstackConnectorConfig
from onyx.connectors.box.config import BoxConnectorConfig
from onyx.connectors.coda.config import CodaConnectorConfig
from onyx.connectors.confluence.config import ConfluenceConnectorConfig
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.discord.config import DiscordConnectorConfig
from onyx.connectors.discourse.config import DiscourseConnectorConfig
from onyx.connectors.document360.config import Document360ConnectorConfig
from onyx.connectors.dropbox.config import DropboxConnectorConfig
from onyx.connectors.drupal_wiki.config import DrupalWikiConnectorConfig
from onyx.connectors.egnyte.config import EgnyteConnectorConfig
from onyx.connectors.file.config import LocalFileConnectorConfig
from onyx.connectors.fireflies.config import FirefliesConnectorConfig
from onyx.connectors.gitbook.config import GitbookConnectorConfig
from onyx.connectors.gmail.config import GmailConnectorConfig
from onyx.connectors.gong.config import GongConnectorConfig
from onyx.connectors.google_drive.config import GoogleDriveConnectorConfig
from onyx.connectors.google_site.config import GoogleSitesConnectorConfig
from onyx.connectors.guru.config import GuruConnectorConfig
from onyx.connectors.highspot.config import HighspotConnectorConfig
from onyx.connectors.imap.config import ImapConnectorConfig
from onyx.connectors.loopio.config import LoopioConnectorConfig
from onyx.connectors.lumapps.config import LumAppsConnectorConfig
from onyx.connectors.mediawiki.config import MediaWikiConnectorConfig
from onyx.connectors.mock_connector.config import MockConnectorConfig
from onyx.connectors.notion.config import NotionConnectorConfig
from onyx.connectors.outline.config import OutlineConnectorConfig
from onyx.connectors.outlook.config import OutlookConnectorConfig
from onyx.connectors.sharepoint.config import SharepointConnectorConfig
from onyx.connectors.slab.config import SlabConnectorConfig
from onyx.connectors.slack.config import SlackConnectorConfig
from onyx.connectors.teams.config import TeamsConnectorConfig
from onyx.connectors.web.config import WebConnectorConfig
from onyx.connectors.wikipedia.config import WikipediaConnectorConfig
from onyx.connectors.xenforo.config import XenforoConnectorConfig
from onyx.connectors.zoom.config import ZoomConnectorConfig
from onyx.connectors.zulip.config import ZulipConnectorConfig


class ConnectorMapping(BaseModel):
    module_path: str
    class_name: str
    # TODO(evan-onyx): make required once every connector has a typed config.
    config_class: type[ConnectorConfig] | None = None


# Mapping of DocumentSource to connector details for lazy loading
CONNECTOR_CLASS_MAP = {
    DocumentSource.WEB: ConnectorMapping(
        module_path="onyx.connectors.web.connector",
        class_name="WebConnector",
        config_class=WebConnectorConfig,
    ),
    DocumentSource.FILE: ConnectorMapping(
        module_path="onyx.connectors.file.connector",
        class_name="LocalFileConnector",
        config_class=LocalFileConnectorConfig,
    ),
    DocumentSource.SLACK: ConnectorMapping(
        module_path="onyx.connectors.slack.connector",
        class_name="SlackConnector",
        config_class=SlackConnectorConfig,
    ),
    DocumentSource.GITHUB: ConnectorMapping(
        module_path="onyx.connectors.github.connector",
        class_name="GithubConnector",
    ),
    DocumentSource.GMAIL: ConnectorMapping(
        module_path="onyx.connectors.gmail.connector",
        class_name="GmailConnector",
        config_class=GmailConnectorConfig,
    ),
    DocumentSource.GITLAB: ConnectorMapping(
        module_path="onyx.connectors.gitlab.connector",
        class_name="GitlabConnector",
    ),
    DocumentSource.GITBOOK: ConnectorMapping(
        module_path="onyx.connectors.gitbook.connector",
        class_name="GitbookConnector",
        config_class=GitbookConnectorConfig,
    ),
    DocumentSource.GOOGLE_DRIVE: ConnectorMapping(
        module_path="onyx.connectors.google_drive.connector",
        class_name="GoogleDriveConnector",
        config_class=GoogleDriveConnectorConfig,
    ),
    DocumentSource.BOOKSTACK: ConnectorMapping(
        module_path="onyx.connectors.bookstack.connector",
        class_name="BookstackConnector",
        config_class=BookstackConnectorConfig,
    ),
    DocumentSource.OUTLINE: ConnectorMapping(
        module_path="onyx.connectors.outline.connector",
        class_name="OutlineConnector",
        config_class=OutlineConnectorConfig,
    ),
    DocumentSource.CONFLUENCE: ConnectorMapping(
        module_path="onyx.connectors.confluence.connector",
        class_name="ConfluenceConnector",
        config_class=ConfluenceConnectorConfig,
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
        config_class=SlabConnectorConfig,
    ),
    DocumentSource.CODA: ConnectorMapping(
        module_path="onyx.connectors.coda.connector",
        class_name="CodaConnector",
        config_class=CodaConnectorConfig,
    ),
    DocumentSource.CANVAS: ConnectorMapping(
        module_path="onyx.connectors.canvas.connector",
        class_name="CanvasConnector",
    ),
    DocumentSource.NOTION: ConnectorMapping(
        module_path="onyx.connectors.notion.connector",
        class_name="NotionConnector",
        config_class=NotionConnectorConfig,
    ),
    DocumentSource.ZULIP: ConnectorMapping(
        module_path="onyx.connectors.zulip.connector",
        class_name="ZulipConnector",
        config_class=ZulipConnectorConfig,
    ),
    DocumentSource.GURU: ConnectorMapping(
        module_path="onyx.connectors.guru.connector",
        class_name="GuruConnector",
        config_class=GuruConnectorConfig,
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
        config_class=Document360ConnectorConfig,
    ),
    DocumentSource.GONG: ConnectorMapping(
        module_path="onyx.connectors.gong.connector",
        class_name="GongConnector",
        config_class=GongConnectorConfig,
    ),
    DocumentSource.GOOGLE_SITES: ConnectorMapping(
        module_path="onyx.connectors.google_site.connector",
        class_name="GoogleSitesConnector",
        config_class=GoogleSitesConnectorConfig,
    ),
    DocumentSource.ZENDESK: ConnectorMapping(
        module_path="onyx.connectors.zendesk.connector",
        class_name="ZendeskConnector",
    ),
    DocumentSource.LOOPIO: ConnectorMapping(
        module_path="onyx.connectors.loopio.connector",
        class_name="LoopioConnector",
        config_class=LoopioConnectorConfig,
    ),
    DocumentSource.BOX: ConnectorMapping(
        module_path="onyx.connectors.box.connector",
        class_name="BoxConnector",
        config_class=BoxConnectorConfig,
    ),
    DocumentSource.DROPBOX: ConnectorMapping(
        module_path="onyx.connectors.dropbox.connector",
        class_name="DropboxConnector",
        config_class=DropboxConnectorConfig,
    ),
    DocumentSource.SHAREPOINT: ConnectorMapping(
        module_path="onyx.connectors.sharepoint.connector",
        class_name="SharepointConnector",
        config_class=SharepointConnectorConfig,
    ),
    DocumentSource.ONEDRIVE: ConnectorMapping(
        module_path="onyx.connectors.onedrive.connector",
        class_name="OneDriveConnector",
    ),
    DocumentSource.TEAMS: ConnectorMapping(
        module_path="onyx.connectors.teams.connector",
        class_name="TeamsConnector",
        config_class=TeamsConnectorConfig,
    ),
    DocumentSource.OUTLOOK: ConnectorMapping(
        module_path="onyx.connectors.outlook.connector",
        class_name="OutlookConnector",
        config_class=OutlookConnectorConfig,
    ),
    DocumentSource.SALESFORCE: ConnectorMapping(
        module_path="onyx.connectors.salesforce.connector",
        class_name="SalesforceConnector",
    ),
    DocumentSource.DISCOURSE: ConnectorMapping(
        module_path="onyx.connectors.discourse.connector",
        class_name="DiscourseConnector",
        config_class=DiscourseConnectorConfig,
    ),
    DocumentSource.AXERO: ConnectorMapping(
        module_path="onyx.connectors.axero.connector",
        class_name="AxeroConnector",
        config_class=AxeroConnectorConfig,
    ),
    DocumentSource.CLICKUP: ConnectorMapping(
        module_path="onyx.connectors.clickup.connector",
        class_name="ClickupConnector",
    ),
    DocumentSource.MEDIAWIKI: ConnectorMapping(
        module_path="onyx.connectors.mediawiki.wiki",
        class_name="MediaWikiConnector",
        config_class=MediaWikiConnectorConfig,
    ),
    DocumentSource.WIKIPEDIA: ConnectorMapping(
        module_path="onyx.connectors.wikipedia.connector",
        class_name="WikipediaConnector",
        config_class=WikipediaConnectorConfig,
    ),
    DocumentSource.ASANA: ConnectorMapping(
        module_path="onyx.connectors.asana.connector",
        class_name="AsanaConnector",
    ),
    DocumentSource.S3: ConnectorMapping(
        module_path="onyx.connectors.blob.connector",
        class_name="BlobStorageConnector",
        config_class=BlobStorageConnectorConfig,
    ),
    DocumentSource.R2: ConnectorMapping(
        module_path="onyx.connectors.blob.connector",
        class_name="BlobStorageConnector",
        config_class=BlobStorageConnectorConfig,
    ),
    DocumentSource.GOOGLE_CLOUD_STORAGE: ConnectorMapping(
        module_path="onyx.connectors.blob.connector",
        class_name="BlobStorageConnector",
        config_class=BlobStorageConnectorConfig,
    ),
    DocumentSource.OCI_STORAGE: ConnectorMapping(
        module_path="onyx.connectors.blob.connector",
        class_name="BlobStorageConnector",
        config_class=BlobStorageConnectorConfig,
    ),
    DocumentSource.XENFORO: ConnectorMapping(
        module_path="onyx.connectors.xenforo.connector",
        class_name="XenforoConnector",
        config_class=XenforoConnectorConfig,
    ),
    DocumentSource.DISCORD: ConnectorMapping(
        module_path="onyx.connectors.discord.connector",
        class_name="DiscordConnector",
        config_class=DiscordConnectorConfig,
    ),
    DocumentSource.FRESHDESK: ConnectorMapping(
        module_path="onyx.connectors.freshdesk.connector",
        class_name="FreshdeskConnector",
    ),
    DocumentSource.FIREFLIES: ConnectorMapping(
        module_path="onyx.connectors.fireflies.connector",
        class_name="FirefliesConnector",
        config_class=FirefliesConnectorConfig,
    ),
    DocumentSource.ZOOM: ConnectorMapping(
        module_path="onyx.connectors.zoom.connector",
        class_name="ZoomConnector",
        config_class=ZoomConnectorConfig,
    ),
    DocumentSource.EGNYTE: ConnectorMapping(
        module_path="onyx.connectors.egnyte.connector",
        class_name="EgnyteConnector",
        config_class=EgnyteConnectorConfig,
    ),
    DocumentSource.AIRTABLE: ConnectorMapping(
        module_path="onyx.connectors.airtable.airtable_connector",
        class_name="AirtableConnector",
    ),
    DocumentSource.HIGHSPOT: ConnectorMapping(
        module_path="onyx.connectors.highspot.connector",
        class_name="HighspotConnector",
        config_class=HighspotConnectorConfig,
    ),
    DocumentSource.DRUPAL_WIKI: ConnectorMapping(
        module_path="onyx.connectors.drupal_wiki.connector",
        class_name="DrupalWikiConnector",
        config_class=DrupalWikiConnectorConfig,
    ),
    DocumentSource.IMAP: ConnectorMapping(
        module_path="onyx.connectors.imap.connector",
        class_name="ImapConnector",
        config_class=ImapConnectorConfig,
    ),
    DocumentSource.BITBUCKET: ConnectorMapping(
        module_path="onyx.connectors.bitbucket.connector",
        class_name="BitbucketConnector",
    ),
    DocumentSource.TESTRAIL: ConnectorMapping(
        module_path="onyx.connectors.testrail.connector",
        class_name="TestRailConnector",
    ),
    DocumentSource.BRAINTRUST: ConnectorMapping(
        module_path="onyx.connectors.braintrust.connector",
        class_name="BraintrustConnector",
    ),
    DocumentSource.LUMAPPS: ConnectorMapping(
        module_path="onyx.connectors.lumapps.connector",
        class_name="LumAppsConnector",
        config_class=LumAppsConnectorConfig,
    ),
    # just for integration tests
    DocumentSource.MOCK_CONNECTOR: ConnectorMapping(
        module_path="onyx.connectors.mock_connector.connector",
        class_name="MockConnector",
        config_class=MockConnectorConfig,
    ),
}
