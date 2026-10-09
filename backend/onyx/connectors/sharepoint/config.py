from typing import Annotated

from onyx.configs.app_configs import (
    INDEX_BATCH_SIZE,
    SHAREPOINT_EXHAUSTIVE_AD_ENUMERATION,
)
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeExclude,
    ScopeInclude,
    ScopeToggle,
)
from onyx.connectors.microsoft_utils.config import (
    DEFAULT_SHAREPOINT_DOMAIN_SUFFIX,
    MicrosoftCloudBinding,
)

_COSMETIC = FieldPolicy(FieldClass.COSMETIC)
_CONTENT_TYPE_TOGGLE = FieldPolicy(
    FieldClass.SCOPE, scope=ScopeToggle(widens_when=True)
)


class SharepointCredentialBinding(MicrosoftCloudBinding):
    # Ignored: the connector uses the suffix of the cloud graph_api_host selects.
    sharepoint_domain_suffix: Annotated[str, _COSMETIC] = (
        DEFAULT_SHAREPOINT_DOMAIN_SUFFIX
    )


class SharepointConnectorConfig(SharepointCredentialBinding, ConnectorConfig):
    batch_size: Annotated[int, _COSMETIC] = INDEX_BATCH_SIZE
    sites: Annotated[
        list[str] | None,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=True)),
    ] = None
    excluded_sites: Annotated[
        list[str] | None, FieldPolicy(FieldClass.SCOPE, scope=ScopeExclude())
    ] = None
    excluded_paths: Annotated[
        list[str] | None, FieldPolicy(FieldClass.SCOPE, scope=ScopeExclude())
    ] = None
    include_site_pages: Annotated[bool, _CONTENT_TYPE_TOGGLE] = True
    include_site_documents: Annotated[bool, _CONTENT_TYPE_TOGGLE] = True
    # Changes the access list of indexed documents.
    treat_sharing_link_as_public: Annotated[bool, FieldPolicy(FieldClass.BEHAVIOR)] = (
        False
    )
    # Read only by the EE group sync, not by indexing.
    exhaustive_ad_enumeration: Annotated[bool, _COSMETIC] = (
        SHAREPOINT_EXHAUSTIVE_AD_ENUMERATION
    )
