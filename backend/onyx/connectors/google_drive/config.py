from typing import Annotated

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeDirection,
    ScopeInclude,
    ScopeToggle,
)
from onyx.connectors.planning_rule import ConnectorChangeOverride

_COSMETIC = FieldPolicy(FieldClass.COSMETIC)
_SPECIFIC_REQUEST_FIELDS = (
    "shared_drive_urls",
    "my_drive_emails",
    "shared_folder_urls",
)
_GENERAL_TOGGLE_FIELDS = (
    "include_shared_drives",
    "include_my_drives",
    "include_files_shared_with_me",
)
# The connector ignores the general toggles when a specific request is set.
_GENERAL_TOGGLE = FieldPolicy(
    FieldClass.SCOPE,
    scope=ScopeToggle(widens_when=True),
    depends_on=_SPECIFIC_REQUEST_FIELDS,
)
_SPECIFIC_REQUEST = FieldPolicy(
    FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=False)
)


class GoogleDriveConnectorConfig(ConnectorConfig):
    include_shared_drives: Annotated[bool, _GENERAL_TOGGLE] = False
    include_my_drives: Annotated[bool, _GENERAL_TOGGLE] = False
    include_files_shared_with_me: Annotated[bool, _GENERAL_TOGGLE] = False
    shared_drive_urls: Annotated[str | None, _SPECIFIC_REQUEST] = None
    my_drive_emails: Annotated[str | None, _SPECIFIC_REQUEST] = None
    shared_folder_urls: Annotated[str | None, _SPECIFIC_REQUEST] = None
    # The users whose drives are walked.
    specific_user_emails: Annotated[
        str | None,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=True)),
    ] = None
    exclude_domain_link_only: Annotated[
        bool, FieldPolicy(FieldClass.SCOPE, scope=ScopeToggle(widens_when=False))
    ] = False
    batch_size: Annotated[int, _COSMETIC] = INDEX_BATCH_SIZE
    # Deprecated: kept so stored legacy configs still validate. The connector
    # ignores them.
    folder_paths: Annotated[list[str] | None, _COSMETIC] = None
    include_shared: Annotated[bool | None, _COSMETIC] = None
    follow_shortcuts: Annotated[bool | None, _COSMETIC] = None
    only_org_public: Annotated[bool | None, _COSMETIC] = None
    continue_on_failure: Annotated[bool | None, _COSMETIC] = None


def _has_specific_requests(config: GoogleDriveConnectorConfig) -> bool:
    return bool(
        config.shared_drive_urls or config.my_drive_emails or config.shared_folder_urls
    )


def google_drive_planning_rule(
    old: GoogleDriveConnectorConfig, new: GoogleDriveConnectorConfig
) -> ConnectorChangeOverride | None:
    # A specific request turns the general toggles off. A change between
    # the general and the specific mode replaces one set of files with
    # another; inside the specific mode the toggles have no effect.
    old_specific = _has_specific_requests(old)
    new_specific = _has_specific_requests(new)
    if old_specific != new_specific:
        return ConnectorChangeOverride(
            scope_directions=dict.fromkeys(
                (*_SPECIFIC_REQUEST_FIELDS, *_GENERAL_TOGGLE_FIELDS),
                ScopeDirection.UNKNOWN,
            )
        )
    if new_specific:
        return ConnectorChangeOverride(
            scope_directions=dict.fromkeys(_GENERAL_TOGGLE_FIELDS, ScopeDirection.NONE)
        )
    return None
