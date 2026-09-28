from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.microsoft_utils.config import (
    DEFAULT_AUTHORITY_HOST,
    DEFAULT_GRAPH_API_HOST,
    DEFAULT_SHAREPOINT_DOMAIN_SUFFIX,
)


class SharepointConnectorConfig(ConnectorConfig):
    batch_size: int = INDEX_BATCH_SIZE
    sites: list[str] | None = None
    excluded_sites: list[str] | None = None
    excluded_paths: list[str] | None = None
    include_site_pages: bool = True
    include_site_documents: bool = True
    treat_sharing_link_as_public: bool = False
    authority_host: str = DEFAULT_AUTHORITY_HOST
    graph_api_host: str = DEFAULT_GRAPH_API_HOST
    sharepoint_domain_suffix: str = DEFAULT_SHAREPOINT_DOMAIN_SUFFIX
