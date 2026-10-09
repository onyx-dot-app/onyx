from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import build_db_credentials_provider
from onyx.connectors.factory import build_connector_kwargs
from onyx.connectors.linear.connector import LinearConnector
from onyx.db.models import ConnectorCredentialPair


def linear_connector(cc_pair: ConnectorCredentialPair) -> LinearConnector:
    """The pair's connector on the DB credential provider, whose rotation lock
    and write-back keep a refreshed OAuth token shared with indexing."""
    connector = LinearConnector(
        **build_connector_kwargs(
            cc_pair.connector.source, cc_pair.connector.connector_specific_config
        )
    )
    connector.set_credentials_provider(
        build_db_credentials_provider(DocumentSource.LINEAR, cc_pair.credential.id)
    )
    return connector
