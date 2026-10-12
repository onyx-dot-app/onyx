from typing import Annotated

from onyx.connectors.connector_config import ConnectorConfig, RealmCredentialBinding
from onyx.connectors.field_policy import FieldClass, FieldPolicy, ScopeInclude


class GongCredentialBinding(RealmCredentialBinding):
    REALM_KEY = "gong_base_url"
    DEFAULT_REALM = "https://api.gong.io"

    # Where the account works. The connector reads it from the credential.
    gong_base_url: Annotated[str | None, FieldPolicy(FieldClass.COSMETIC)] = None


class GongConnectorConfig(GongCredentialBinding, ConnectorConfig):
    workspaces: Annotated[
        list[str] | None,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=True)),
    ] = None
    # Replaces speaker names in transcripts.
    hide_user_info: Annotated[bool, FieldPolicy(FieldClass.BEHAVIOR)] = False
