from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import build_db_credentials_provider
from onyx.connectors.factory import build_connector_kwargs
from onyx.connectors.youtrack.connector import YouTrackConnector
from onyx.db.models import ConnectorCredentialPair


def youtrack_connector(cc_pair: ConnectorCredentialPair) -> YouTrackConnector:
    connector = YouTrackConnector(
        **build_connector_kwargs(
            cc_pair.connector.source, cc_pair.connector.connector_specific_config
        )
    )
    connector.set_credentials_provider(
        build_db_credentials_provider(DocumentSource.YOUTRACK, cc_pair.credential.id)
    )
    return connector
