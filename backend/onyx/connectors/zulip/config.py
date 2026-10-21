from typing import Annotated

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig, CredentialBinding
from onyx.connectors.field_policy import FieldClass, FieldPolicy


class ZulipCredentialBinding(CredentialBinding):
    # The connector stores it but does not use it.
    realm_name: Annotated[str, FieldPolicy(FieldClass.COSMETIC)]
    # Used only to build message links; the zuliprc credential picks the server.
    realm_url: Annotated[str, FieldPolicy(FieldClass.BEHAVIOR)]


class ZulipConnectorConfig(ZulipCredentialBinding, ConnectorConfig):
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE
