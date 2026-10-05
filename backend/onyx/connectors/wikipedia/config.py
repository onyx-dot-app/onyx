from typing import Annotated

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeInclude,
    ScopeOpaque,
)

_TARGETS = FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=False))


class WikipediaConnectorConfig(ConnectorConfig):
    categories: Annotated[list[str], _TARGETS]
    pages: Annotated[list[str], _TARGETS]
    # -1 is unbounded; a deeper recursion widens.
    recurse_depth: Annotated[int, FieldPolicy(FieldClass.SCOPE, scope=ScopeOpaque())]
    # Document ids contain the page URL, which the language subdomain selects.
    language_code: Annotated[str, FieldPolicy(FieldClass.IDENTITY)] = "en"
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE
