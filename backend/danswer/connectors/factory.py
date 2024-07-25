from typing import Any
from typing import Type

from sqlalchemy.orm import Session

from danswer.configs.constants import DocumentSource
from danswer.connectors.axero.connector import AxeroConnector
from danswer.connectors.blob.connector import BlobStorageConnector
from danswer.connectors.bookstack.connector import BookstackConnector
from danswer.connectors.clickup.connector import ClickupConnector
from danswer.connectors.confluence.connector import ConfluenceConnector
from danswer.connectors.danswer_jira.connector import JiraConnector
from danswer.connectors.discourse.connector import DiscourseConnector
from danswer.connectors.document360.connector import Document360Connector
from danswer.connectors.dropbox.connector import DropboxConnector
from danswer.connectors.file.connector import LocalFileConnector
from danswer.connectors.github.connector import GithubConnector
from danswer.connectors.gitlab.connector import GitlabConnector
from danswer.connectors.gmail.connector import GmailConnector
from danswer.connectors.gong.connector import GongConnector
from danswer.connectors.google_drive.connector import GoogleDriveConnector
from danswer.connectors.google_site.connector import GoogleSitesConnector
from danswer.connectors.guru.connector import GuruConnector
from danswer.connectors.hubspot.connector import HubSpotConnector
from danswer.connectors.interfaces import BaseConnector
from danswer.connectors.interfaces import EventConnector
from danswer.connectors.interfaces import LoadConnector
from danswer.connectors.interfaces import PollConnector
from danswer.connectors.linear.connector import LinearConnector
from danswer.connectors.loopio.connector import LoopioConnector
from danswer.connectors.mediawiki.wiki import MediaWikiConnector
from danswer.connectors.models import InputType
from danswer.connectors.notion.connector import NotionConnector
from danswer.connectors.productboard.connector import ProductboardConnector
from danswer.connectors.requesttracker.connector import RequestTrackerConnector
from danswer.connectors.salesforce.connector import SalesforceConnector
from danswer.connectors.sharepoint.connector import SharepointConnector
from danswer.connectors.slab.connector import SlabConnector
from danswer.connectors.slack.connector import SlackPollConnector
from danswer.connectors.slack.load_connector import SlackLoadConnector
from danswer.connectors.teams.connector import TeamsConnector
from danswer.connectors.web.connector import WebConnector
from danswer.connectors.wikipedia.connector import WikipediaConnector
from danswer.connectors.zendesk.connector import ZendeskConnector
from danswer.connectors.zulip.connector import ZulipConnector
from danswer.db.credentials import backend_update_credential_json
from danswer.db.models import Credential


class ConnectorMissingException(Exception):
    pass


def identify_connector_class(
    source: DocumentSource,
    input_type: InputType | None = None,
) -> Type[BaseConnector]:
    connector_map = {
        DocumentSource.WEB: WebConnector,
        DocumentSource.FILE: LocalFileConnector,
        DocumentSource.SLACK: {
            InputType.LOAD_STATE: SlackLoadConnector,
            InputType.POLL: SlackPollConnector,
        },
        DocumentSource.GITHUB: GithubConnector,
        DocumentSource.GMAIL: GmailConnector,
        DocumentSource.GITLAB: GitlabConnector,
        DocumentSource.GOOGLE_DRIVE: GoogleDriveConnector,
        DocumentSource.BOOKSTACK: BookstackConnector,
        DocumentSource.CONFLUENCE: ConfluenceConnector,
        DocumentSource.JIRA: JiraConnector,
        DocumentSource.PRODUCTBOARD: ProductboardConnector,
        DocumentSource.SLAB: SlabConnector,
        DocumentSource.NOTION: NotionConnector,
        DocumentSource.ZULIP: ZulipConnector,
        DocumentSource.REQUESTTRACKER: RequestTrackerConnector,
        DocumentSource.GURU: GuruConnector,
        DocumentSource.LINEAR: LinearConnector,
        DocumentSource.HUBSPOT: HubSpotConnector,
        DocumentSource.DOCUMENT360: Document360Connector,
        DocumentSource.GONG: GongConnector,
        DocumentSource.GOOGLE_SITES: GoogleSitesConnector,
        DocumentSource.ZENDESK: ZendeskConnector,
        DocumentSource.LOOPIO: LoopioConnector,
        DocumentSource.DROPBOX: DropboxConnector,
        DocumentSource.SHAREPOINT: SharepointConnector,
        DocumentSource.TEAMS: TeamsConnector,
        DocumentSource.SALESFORCE: SalesforceConnector,
        DocumentSource.DISCOURSE: DiscourseConnector,
        DocumentSource.AXERO: AxeroConnector,
        DocumentSource.CLICKUP: ClickupConnector,
        DocumentSource.MEDIAWIKI: MediaWikiConnector,
        DocumentSource.WIKIPEDIA: WikipediaConnector,
        DocumentSource.S3: BlobStorageConnector,
        DocumentSource.R2: BlobStorageConnector,
        DocumentSource.GOOGLE_CLOUD_STORAGE: BlobStorageConnector,
        DocumentSource.OCI_STORAGE: BlobStorageConnector,
    }
    connector_by_source = connector_map.get(source, {})

    if isinstance(connector_by_source, dict):
        if input_type is None:
            # If not specified, default to most exhaustive update
            connector = connector_by_source.get(InputType.LOAD_STATE)
        else:
            connector = connector_by_source.get(input_type)
    else:
        connector = connector_by_source
    if connector is None:
        raise ConnectorMissingException(f"Connector not found for source={source}")

    if any(
        [
            input_type == InputType.LOAD_STATE
            and not issubclass(connector, LoadConnector),
            input_type == InputType.POLL and not issubclass(connector, PollConnector),
            input_type == InputType.EVENT and not issubclass(connector, EventConnector),
        ]
    ):
        raise ConnectorMissingException(
            f"Connector for source={source} does not accept input_type={input_type}"
        )
    return connector


def instantiate_connector(
    source: DocumentSource,
    input_type: InputType,
    connector_specific_config: dict[str, Any],
    credential: Credential,
    db_session: Session,
) -> BaseConnector:
    connector_class = identify_connector_class(source, input_type)
    connector = connector_class(**connector_specific_config)
    new_credentials = connector.load_credentials(credential.credential_json)

    if new_credentials is not None:
        backend_update_credential_json(credential, new_credentials, db_session)

    return connector
