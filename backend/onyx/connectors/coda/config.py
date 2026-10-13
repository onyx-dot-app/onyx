from typing import Annotated

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import FieldClass, FieldPolicy, ScopeInclude


class CodaConnectorConfig(ConnectorConfig):
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE
    # When off, page documents are still indexed, with no text.
    index_page_content: Annotated[bool, FieldPolicy(FieldClass.BEHAVIOR)] = True
    # A filter on the doc list; document ids do not hold it.
    workspace_id: Annotated[
        str | None,
        FieldPolicy(
            FieldClass.SCOPE,
            scope=ScopeInclude(empty_means_all=True, split_on_commas=False),
        ),
    ] = None
