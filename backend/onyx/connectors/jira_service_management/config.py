from typing import Annotated

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeInclude,
)


class JiraServiceManagementConnectorConfig(ConnectorConfig):
    # JSM service desk to pull requests from. Empty indexes every desk the
    # credential can read.
    service_desk_id: Annotated[
        str | None,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=True)),
    ] = None
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE
    # v1 indexes request bodies + public comments only; no attachment
    # enumeration path exists yet, so attachments are off by construction.
    # Kept so a future attachment pass follows the shared opt-in convention.
    include_attachments: Annotated[bool, FieldPolicy(FieldClass.BEHAVIOR)] = False
