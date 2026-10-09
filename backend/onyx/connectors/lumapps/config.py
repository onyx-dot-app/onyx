from typing import Annotated

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import BaseUrlCredentialBinding, ConnectorConfig
from onyx.connectors.field_policy import FieldClass, FieldPolicy, ScopeInclude

_IDENTITY = FieldPolicy(FieldClass.IDENTITY)
_FILTER = FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=True))


class LumAppsCredentialBinding(BaseUrlCredentialBinding):
    # Content uids (the document ids) resolve only within one site and organization.
    base_url: Annotated[str, _IDENTITY]
    organization_id: Annotated[str, _IDENTITY]


class LumAppsConnectorConfig(LumAppsCredentialBinding, ConnectorConfig):
    instance_ids: Annotated[list[str] | None, _FILTER] = None
    custom_content_types: Annotated[list[str] | None, _FILTER] = None
    # Picks the text of each document; it also goes to the content list request.
    lang: Annotated[str, FieldPolicy(FieldClass.BEHAVIOR)] = "en"
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE
