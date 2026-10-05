from typing import Annotated

from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import FieldClass, FieldPolicy


class XenforoConnectorConfig(ConnectorConfig):
    # The board or thread URL that is crawled.
    base_url: Annotated[str, FieldPolicy(FieldClass.IDENTITY)]
