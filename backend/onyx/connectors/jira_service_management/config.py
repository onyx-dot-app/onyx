from typing import Annotated

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig, CredentialBinding
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeInclude,
    ScopeExclude,
)

class JSMCredentialBinding(CredentialBinding):
    jsm_base_url: Annotated[str, FieldPolicy(FieldClass.IDENTITY)]
    jsm_user_email: Annotated[str, FieldPolicy(FieldClass.IDENTITY)]
    jsm_api_token: Annotated[str, FieldPolicy(FieldClass.CREDENTIAL)]

class JSMConnectorConfig(JSMCredentialBinding, ConnectorConfig):
    project_key: Annotated[
        str | None,
        FieldPolicy(
            FieldClass.SCOPE,
            scope=ScopeInclude(empty_means_all=True),
        ),
    ] = None
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE
    labels_to_skip: Annotated[
        list[str], FieldPolicy(FieldClass.SCOPE, scope=ScopeExclude())
    ] = []
