from onyx.configs.constants import DocumentSource
from onyx.configs.llm_configs import get_image_extraction_and_analysis_enabled
from onyx.connectors.credentials_provider import build_db_credentials_provider
from onyx.connectors.factory import build_connector_kwargs
from onyx.connectors.smb.connector import SmbConnector
from onyx.db.models import ConnectorCredentialPair


def smb_connector(cc_pair: ConnectorCredentialPair) -> SmbConnector:
    connector = SmbConnector(
        **build_connector_kwargs(
            cc_pair.connector.source, cc_pair.connector.connector_specific_config
        )
    )
    # The slim listing must admit the image files that indexing admitted.
    connector.set_allow_images(get_image_extraction_and_analysis_enabled())
    connector.set_credentials_provider(
        build_db_credentials_provider(DocumentSource.SMB, cc_pair.credential.id)
    )
    return connector
