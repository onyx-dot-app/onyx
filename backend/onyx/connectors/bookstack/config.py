from typing import Annotated

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig, RealmCredentialBinding
from onyx.connectors.field_policy import FieldClass, FieldPolicy


class BookstackCredentialBinding(RealmCredentialBinding):
    REALM_KEY = "bookstack_base_url"

    # Where the account works. The connector reads it from the credential.
    bookstack_base_url: Annotated[str | None, FieldPolicy(FieldClass.COSMETIC)] = None


class BookstackConnectorConfig(BookstackCredentialBinding, ConnectorConfig):
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE
