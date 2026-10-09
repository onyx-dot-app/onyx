from enum import StrEnum

from onyx.connectors.connector_config import ConnectorConfig


class ZendeskContentType(StrEnum):
    ARTICLES = "articles"
    TICKETS = "tickets"


class ZendeskConnectorConfig(ConnectorConfig):
    content_type: ZendeskContentType = ZendeskContentType.ARTICLES
    calls_per_minute: int | None = None
