from typing import Annotated

from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import FieldClass, FieldPolicy, ScopeOpaque


class XenforoConnectorConfig(ConnectorConfig):
    # The board or thread URL that is crawled. Document ids do not hold it.
    base_url: Annotated[str, FieldPolicy(FieldClass.SCOPE, scope=ScopeOpaque())]
