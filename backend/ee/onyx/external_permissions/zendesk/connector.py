from ee.onyx.external_permissions.utils import credential_json
from onyx.connectors.factory import build_connector_kwargs
from onyx.connectors.zendesk.connector import ZendeskConnector
from onyx.db.models import ConnectorCredentialPair


def zendesk_connector(cc_pair: ConnectorCredentialPair) -> ZendeskConnector:
    connector = ZendeskConnector(
        **build_connector_kwargs(
            cc_pair.connector.source, cc_pair.connector.connector_specific_config
        )
    )
    connector.load_credentials(credential_json(cc_pair))
    return connector
