from typing import Annotated

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import FieldClass, FieldPolicy


class GoogleSitesConnectorConfig(ConnectorConfig):
    # The zip is the whole source: a new zip needs a re-index and a prune.
    zip_path: Annotated[str, FieldPolicy(FieldClass.IDENTITY)]
    # Used only to build page links.
    base_url: Annotated[str, FieldPolicy(FieldClass.BEHAVIOR)]
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE
