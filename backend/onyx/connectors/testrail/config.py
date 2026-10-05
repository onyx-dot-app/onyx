from typing import Annotated, Any

from pydantic import field_validator

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeInclude,
    ScopeOpaque,
)

# A numeric limit: no descriptor compares the old and new values.
_LIMIT = FieldPolicy(FieldClass.SCOPE, scope=ScopeOpaque())


class TestRailConnectorConfig(ConnectorConfig):
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE
    # A blank string or None fetches every project. A list ([] fetches none)
    # comes only from the API.
    project_ids: Annotated[
        str | list[int] | None,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=True)),
    ] = None
    # Matters only when max_pages cuts the case list short.
    cases_page_size: Annotated[int | None, FieldPolicy(FieldClass.COSMETIC)] = None
    # A cap on case pages per project and suite.
    max_pages: Annotated[int | None, _LIMIT] = None
    # Cases with more text than this are skipped.
    skip_doc_absolute_chars: Annotated[int | None, _LIMIT] = None

    # The constructor treats a blank string like None (use the default).
    @field_validator(
        "cases_page_size", "max_pages", "skip_doc_absolute_chars", mode="before"
    )
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value
