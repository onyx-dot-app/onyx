from typing import Annotated

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig, CredentialBinding
from onyx.connectors.field_policy import FieldClass, FieldPolicy


class CanvasCredentialBinding(CredentialBinding):
    # Document ids hold only course and item ids, so the URL picks the instance.
    canvas_base_url: Annotated[str, FieldPolicy(FieldClass.IDENTITY)]


class CanvasConnectorConfig(CanvasCredentialBinding, ConnectorConfig):
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE
