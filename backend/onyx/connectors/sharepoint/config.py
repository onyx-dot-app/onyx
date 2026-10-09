from onyx.configs.app_configs import (
    INDEX_BATCH_SIZE,
    SHAREPOINT_EXHAUSTIVE_AD_ENUMERATION,
)
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.microsoft_utils.config import (
    DEFAULT_SHAREPOINT_DOMAIN_SUFFIX,
    MicrosoftCloudBinding,
)


class SharepointCredentialBinding(MicrosoftCloudBinding):
    sharepoint_domain_suffix: str = DEFAULT_SHAREPOINT_DOMAIN_SUFFIX


class SharepointConnectorConfig(SharepointCredentialBinding, ConnectorConfig):
    batch_size: int = INDEX_BATCH_SIZE
    sites: list[str] | None = None
    excluded_sites: list[str] | None = None
    excluded_paths: list[str] | None = None
    include_site_pages: bool = True
    include_site_documents: bool = True
    treat_sharing_link_as_public: bool = False
    exhaustive_ad_enumeration: bool = SHAREPOINT_EXHAUSTIVE_AD_ENUMERATION
