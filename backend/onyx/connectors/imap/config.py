import os

from onyx.connectors.connector_config import ConnectorConfig

DEFAULT_IMAP_PORT_NUMBER = int(os.environ.get("IMAP_PORT", 993))


class ImapConnectorConfig(ConnectorConfig):
    host: str
    port: int = DEFAULT_IMAP_PORT_NUMBER
    mailboxes: list[str] | None = None
