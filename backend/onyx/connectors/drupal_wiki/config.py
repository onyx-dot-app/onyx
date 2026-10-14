from typing import Annotated

from pydantic import ConfigDict

from onyx.configs.app_configs import CONTINUE_ON_CONNECTOR_FAILURE, INDEX_BATCH_SIZE
from onyx.connectors.connector_config import BaseUrlCredentialBinding, ConnectorConfig
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeDirection,
    ScopeInclude,
)
from onyx.connectors.planning_rule import ConnectorChangeOverride

_COSMETIC = FieldPolicy(FieldClass.COSMETIC)
# Attachments and images become sections of their page's document.
_BEHAVIOR = FieldPolicy(FieldClass.BEHAVIOR)
# Empty means "all spaces" only when the other list is also empty;
# drupal_wiki_planning_rule handles that case.
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


def _indexes_all_spaces(config: DrupalWikiConnectorConfig) -> bool:
    return not config.spaces and not config.pages


def drupal_wiki_planning_rule(
    old: DrupalWikiConnectorConfig, new: DrupalWikiConnectorConfig
) -> ConnectorChangeOverride | None:
    old_all = _indexes_all_spaces(old)
    new_all = _indexes_all_spaces(new)
    if old_all == new_all:
        return None
    direction = ScopeDirection.WIDEN if new_all else ScopeDirection.NARROW
    directions: dict[str, ScopeDirection] = {}
    if old.spaces != new.spaces:
        directions["spaces"] = direction
    if old.pages != new.pages:
        directions["pages"] = direction
    return ConnectorChangeOverride(scope_directions=directions)
