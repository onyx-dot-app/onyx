from typing import Annotated, ClassVar

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig, CredentialBinding
from onyx.connectors.field_policy import FieldClass, FieldPolicy, ScopeInclude

_IDENTITY = FieldPolicy(FieldClass.IDENTITY)
_FILTER = FieldPolicy(
    FieldClass.SCOPE,
    scope=ScopeInclude(empty_means_all=True, split_on_commas=False),
)


class JiraServiceManagementCredentialBinding(CredentialBinding):
    site_url_fields: ClassVar[frozenset[str]] = frozenset({"jsm_base_url"})

    jsm_base_url: Annotated[str, _IDENTITY]


class JiraServiceManagementConnectorConfig(
    JiraServiceManagementCredentialBinding, ConnectorConfig
):
    service_desk_id: Annotated[str | None, _FILTER] = None
    request_type_id: Annotated[str | None, _FILTER] = None
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE
