from typing import Annotated

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import BaseUrlCredentialBinding, ConnectorConfig
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeInclude,
    ScopeOpaque,
    ScopeOrdered,
)

from onyx.connectors.seafile.constants import SEAFILE_DEFAULT_MAX_FILE_SIZE_BYTES


class SeafileConnectorConfig(BaseUrlCredentialBinding, ConnectorConfig):
    repo_ids: Annotated[
        list[str], FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=False))
    ]
    path_prefixes: Annotated[
        list[str] | None, FieldPolicy(FieldClass.SCOPE, scope=ScopeOpaque())
    ] = None
    allowed_extensions: Annotated[
        list[str] | None, FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=True))
    ] = None
    max_file_size_bytes: Annotated[
        int, FieldPolicy(FieldClass.SCOPE, scope=ScopeOrdered(widens_when_larger=True))
    ] = SEAFILE_DEFAULT_MAX_FILE_SIZE_BYTES
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE
