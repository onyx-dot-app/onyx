from typing import Annotated

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig, RealmCredentialBinding
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeInclude,
    ScopeToggle,
)

_CONTENT_TYPE_TOGGLE = FieldPolicy(
    FieldClass.SCOPE, scope=ScopeToggle(widens_when=True)
)


class AxeroCredentialBinding(RealmCredentialBinding):
    REALM_KEY = "base_url"

    # Where the account works. The connector reads it from the credential.
    base_url: Annotated[str | None, FieldPolicy(FieldClass.COSMETIC)] = None


class AxeroConnectorConfig(AxeroCredentialBinding, ConnectorConfig):
    spaces: Annotated[
        list[str] | None,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=True)),
    ] = None
    include_article: Annotated[bool, _CONTENT_TYPE_TOGGLE] = True
    include_blog: Annotated[bool, _CONTENT_TYPE_TOGGLE] = True
    include_wiki: Annotated[bool, _CONTENT_TYPE_TOGGLE] = True
    include_forum: Annotated[bool, _CONTENT_TYPE_TOGGLE] = True
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE
