from typing import Annotated

from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeExclude,
    ScopeInclude,
)
from onyx.connectors.microsoft_utils.config import MicrosoftCloudBinding


class OneDriveConnectorConfig(MicrosoftCloudBinding, ConnectorConfig):
    users: Annotated[
        list[str] | None,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=True)),
    ] = None
    excluded_paths: Annotated[
        list[str] | None, FieldPolicy(FieldClass.SCOPE, scope=ScopeExclude())
    ] = None
    # Changes the access list of indexed documents.
    treat_organization_link_as_public: Annotated[
        bool, FieldPolicy(FieldClass.BEHAVIOR)
    ] = False
