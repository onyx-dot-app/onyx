from pydantic import ConfigDict

from onyx.configs.app_configs import CONTINUE_ON_CONNECTOR_FAILURE, INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig


class DrupalWikiConnectorConfig(ConnectorConfig):
    model_config = ConfigDict(extra="allow")

    base_url: str
    spaces: list[str] | None = None
    pages: list[str] | None = None
    batch_size: int = INDEX_BATCH_SIZE
    continue_on_failure: bool = CONTINUE_ON_CONNECTOR_FAILURE
    include_attachments: bool = False
    allow_images: bool = False
