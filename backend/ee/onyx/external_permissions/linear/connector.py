from ee.onyx.external_permissions.utils import load_cc_pair_credentials
from onyx.connectors.factory import build_connector_kwargs
from onyx.connectors.linear.connector import LinearConnector
from onyx.db.models import ConnectorCredentialPair


def linear_connector(cc_pair: ConnectorCredentialPair) -> LinearConnector:
    """The pair's connector with its credential loaded, and stored again if
    loading refreshed it."""
    connector = LinearConnector(
        **build_connector_kwargs(
            cc_pair.connector.source, cc_pair.connector.connector_specific_config
        )
    )
    load_cc_pair_credentials(connector, cc_pair)
    return connector
