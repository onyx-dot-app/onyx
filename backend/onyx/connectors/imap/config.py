import os
from typing import Annotated

from onyx.connectors.connector_config import ConnectorConfig, CredentialBinding
from onyx.connectors.field_policy import FieldClass, FieldPolicy, ScopeInclude

DEFAULT_IMAP_PORT_NUMBER = int(os.environ.get("IMAP_PORT", 993))


class ImapCredentialBinding(CredentialBinding):
    # Document ids are Message-ID headers, so the server picks what they resolve to.
    host: Annotated[str, FieldPolicy(FieldClass.IDENTITY)]
    port: Annotated[int, FieldPolicy(FieldClass.IDENTITY)] = DEFAULT_IMAP_PORT_NUMBER


class ImapConnectorConfig(ImapCredentialBinding, ConnectorConfig):
    mailboxes: Annotated[
        list[str] | None,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=True)),
    ] = None
