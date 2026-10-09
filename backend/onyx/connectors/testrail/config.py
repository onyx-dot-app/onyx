from typing import Any

from pydantic import field_validator

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig


class TestRailConnectorConfig(ConnectorConfig):
    batch_size: int = INDEX_BATCH_SIZE
    project_ids: str | list[int] | None = None
    cases_page_size: int | None = None
    max_pages: int | None = None
    skip_doc_absolute_chars: int | None = None

    # The constructor treats a blank string like None (use the default).
    @field_validator(
        "cases_page_size", "max_pages", "skip_doc_absolute_chars", mode="before"
    )
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value
