from onyx.configs.constants import DocumentSource
from onyx.connectors.azure_datalake.connector import AzureDataLakeConnector
from onyx.connectors.credentials_provider import build_db_credentials_provider
from onyx.connectors.factory import build_connector_kwargs
from onyx.db.models import ConnectorCredentialPair


def azure_datalake_connector(
    cc_pair: ConnectorCredentialPair,
) -> AzureDataLakeConnector:
    connector = AzureDataLakeConnector(
        **build_connector_kwargs(
            cc_pair.connector.source, cc_pair.connector.connector_specific_config
        )
    )
    connector.set_credentials_provider(
        build_db_credentials_provider(
            DocumentSource.AZURE_DATALAKE, cc_pair.credential.id
        )
    )
    return connector
