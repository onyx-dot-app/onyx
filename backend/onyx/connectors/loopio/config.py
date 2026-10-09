from typing import Annotated

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig, RealmCredentialBinding
from onyx.connectors.field_policy import FieldClass, FieldPolicy, ScopeInclude


class LoopioCredentialBinding(RealmCredentialBinding):
    REALM_KEY = "loopio_subdomain"

    # Where the account works. The connector reads it from the credential.
    loopio_subdomain: Annotated[str | None, FieldPolicy(FieldClass.COSMETIC)] = None


class LoopioConnectorConfig(LoopioCredentialBinding, ConnectorConfig):
    # None fetches every stack.
    loopio_stack_name: Annotated[
        str | None,
        FieldPolicy(
            FieldClass.SCOPE,
            scope=ScopeInclude(empty_means_all=True, split_on_commas=False),
        ),
    ] = None
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE
