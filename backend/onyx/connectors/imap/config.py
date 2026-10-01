import os

from onyx.connectors.connector_config import ConnectorConfig, CredentialBinding

DEFAULT_IMAP_PORT_NUMBER = int(os.environ.get("IMAP_PORT", 993))


class ImapCredentialBinding(CredentialBinding):
    host: str
    port: int = DEFAULT_IMAP_PORT_NUMBER


class ImapConnectorConfig(ImapCredentialBinding, ConnectorConfig):
    mailboxes: list[str] | None = None
