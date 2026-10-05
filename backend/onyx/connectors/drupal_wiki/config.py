from typing import Annotated, Self

from pydantic import ConfigDict

from onyx.configs.app_configs import CONTINUE_ON_CONNECTOR_FAILURE, INDEX_BATCH_SIZE
from onyx.connectors.connector_config import BaseUrlCredentialBinding, ConnectorConfig
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeDirection,
    ScopeInclude,
)

_COSMETIC = FieldPolicy(FieldClass.COSMETIC)
# Attachments and images become sections of their page's document.
_BEHAVIOR = FieldPolicy(FieldClass.BEHAVIOR)
# Empty means "all spaces" only when the other list is also empty; the
# classify_scope_change hook handles that case.
_SELECTION = FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=False))


class DrupalWikiConnectorConfig(BaseUrlCredentialBinding, ConnectorConfig):
    model_config = ConfigDict(extra="allow")

    # Document ids are page URLs built from the base URL.
    base_url: Annotated[str, FieldPolicy(FieldClass.IDENTITY)]
    spaces: Annotated[list[str] | None, _SELECTION] = None
    pages: Annotated[list[str] | None, _SELECTION] = None
    batch_size: Annotated[int, _COSMETIC] = INDEX_BATCH_SIZE
    continue_on_failure: Annotated[bool, _COSMETIC] = CONTINUE_ON_CONNECTOR_FAILURE
    include_attachments: Annotated[bool, _BEHAVIOR] = False
    allow_images: Annotated[bool, _BEHAVIOR] = False

    def _indexes_all_spaces(self) -> bool:
        return not self.spaces and not self.pages

    @classmethod
    def classify_scope_change(  # ty: ignore[invalid-method-override]
        cls, old: Self, new: Self
    ) -> dict[str, ScopeDirection]:
        old_all = old._indexes_all_spaces()
        new_all = new._indexes_all_spaces()
        if old_all == new_all:
            return {}
        direction = ScopeDirection.WIDEN if new_all else ScopeDirection.NARROW
        directions: dict[str, ScopeDirection] = {}
        if old.spaces != new.spaces:
            directions["spaces"] = direction
        if old.pages != new.pages:
            directions["pages"] = direction
        return directions
