from typing import Annotated

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import FieldClass, FieldPolicy, ScopeOpaque

# Empty base_id or table_name_or_id indexes every base, and airtable_url
# overrides both, so the direction of a change cannot be derived.
_TABLE_SELECTION = FieldPolicy(FieldClass.SCOPE, scope=ScopeOpaque())
# Only used to build record links.
_LINK = FieldPolicy(FieldClass.BEHAVIOR)


class AirtableConnectorConfig(ConnectorConfig):
    base_id: Annotated[str, _TABLE_SELECTION] = ""
    table_name_or_id: Annotated[str, _TABLE_SELECTION] = ""
    airtable_url: Annotated[str, _TABLE_SELECTION] = ""
    treat_all_non_attachment_fields_as_metadata: Annotated[
        bool, FieldPolicy(FieldClass.BEHAVIOR)
    ] = False
    view_id: Annotated[str | None, _LINK] = None
    share_id: Annotated[str | None, _LINK] = None
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE
