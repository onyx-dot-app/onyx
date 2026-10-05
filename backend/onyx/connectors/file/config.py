from typing import Annotated, Any

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeInclude,
)

_BEHAVIOR = FieldPolicy(FieldClass.BEHAVIOR)


class LocalFileConnectorConfig(ConnectorConfig):
    # The connector also accepts Path entries, but stored JSON only holds str.
    file_locations: Annotated[
        list[str],
        FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=False)),
    ]
    # Display names for the UI only; the connector ignores them.
    file_names: Annotated[list[str] | None, FieldPolicy(FieldClass.COSMETIC)] = None
    # The metadata sets document fields (and can set the document id). An
    # in-place file edit saves the merged metadata as a new file, so adding
    # files to a connector with metadata gives a full re-index.
    zip_metadata_file_id: Annotated[str | None, _BEHAVIOR] = None
    # Deprecated inline metadata: arbitrary JSON keyed by file name.
    zip_metadata: Annotated[dict[str, Any] | None, _BEHAVIOR] = None
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE
