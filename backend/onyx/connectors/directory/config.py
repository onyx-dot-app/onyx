from typing import Annotated

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import FieldClass, FieldPolicy, ScopeInclude

_BEHAVIOR = FieldPolicy(FieldClass.BEHAVIOR)


class DirectoryConnectorConfig(ConnectorConfig):
    """Typed config for the mounted-directory connector (ported from gb10 v4.7.7)."""

    root_directory: Annotated[
        str,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=False)),
    ]
    # Internal source identity; used to build stable document ids, not a UI field.
    source_id: Annotated[str, FieldPolicy(FieldClass.COSMETIC)]
    recursive: Annotated[bool, _BEHAVIOR] = True
    file_extensions: Annotated[list[str] | None, _BEHAVIOR] = None
    include_patterns: Annotated[list[str] | None, _BEHAVIOR] = None
    exclude_patterns: Annotated[list[str] | None, _BEHAVIOR] = None
    exclude_hidden: Annotated[bool, _BEHAVIOR] = True
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE
    max_file_size_mb: Annotated[int, _BEHAVIOR] = 512
    poll_overlap_seconds: Annotated[int, _BEHAVIOR] = 5
    minimum_prune_files: Annotated[int, _BEHAVIOR] = 1
    max_directories_per_batch: Annotated[int, _BEHAVIOR] = 1000
    link_base_url: Annotated[str | None, _BEHAVIOR] = None
