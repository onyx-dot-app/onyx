from typing import Annotated

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import FieldClass, FieldPolicy


class GitbookConnectorConfig(ConnectorConfig):
    # Document ids contain the space id.
    space_id: Annotated[str, FieldPolicy(FieldClass.IDENTITY)]
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE
