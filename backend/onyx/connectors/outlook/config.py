from typing import Annotated

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeDirection,
    ScopeExclude,
    ScopeInclude,
    ScopeOpaque,
    ScopeToggle,
)
from onyx.connectors.microsoft_utils.config import MicrosoftCloudBinding
from onyx.connectors.planning_rule import ConnectorChangeOverride

# The calendar view needs explicit bounds. Past meetings hold the decisions
# people search for, so the window reaches further back than ahead. Pruning
# lists over the same window, so the index holds a rolling calendar.
DEFAULT_CALENDAR_PAST_DAYS = 365
DEFAULT_CALENDAR_FUTURE_DAYS = 180

_CALENDAR_PAST_DAYS = "calendar_past_days"
_CALENDAR_FUTURE_DAYS = "calendar_future_days"
_MAILBOXES = "mailboxes"
_MAILBOX_GROUPS = "mailbox_groups"
# Directions come from outlook_planning_rule: a larger window widens.
_CALENDAR_WINDOW = FieldPolicy(FieldClass.SCOPE, scope=ScopeOpaque())


def _window_direction(
    old_days: int, new_days: int, calendar_on: bool
) -> ScopeDirection:
    if old_days == new_days or not calendar_on:
        return ScopeDirection.NONE
    return ScopeDirection.WIDEN if new_days > old_days else ScopeDirection.NARROW


def _mailbox_items(config: "OutlookConnectorConfig") -> set[tuple[str, str]]:
    return {
        (field_name, name.strip())
        for field_name, names in (
            (_MAILBOXES, config.mailboxes),
            (_MAILBOX_GROUPS, config.mailbox_groups),
        )
        for name in names or []
        if name.strip()
    }


def _mailbox_direction(
    old: "OutlookConnectorConfig", new: "OutlookConnectorConfig"
) -> ScopeDirection:
    """The walked mailboxes are the listed ones plus the members of the listed
    groups. With neither listed, every mailbox is walked."""
    old_items = _mailbox_items(old)
    new_items = _mailbox_items(new)
    if old_items == new_items:
        return ScopeDirection.NONE
    if not old_items:
        return ScopeDirection.NARROW
    if not new_items:
        return ScopeDirection.WIDEN
    added = bool(new_items - old_items)
    removed = bool(old_items - new_items)
    if added and removed:
        return ScopeDirection.BOTH
    return ScopeDirection.WIDEN if added else ScopeDirection.NARROW


class OutlookConnectorConfig(MicrosoftCloudBinding, ConnectorConfig):
    mailboxes: Annotated[
        list[str] | None,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=True)),
    ] = None
    # Entra groups whose members' mailboxes are walked, with the mailboxes
    # above. Directions come from outlook_planning_rule.
    mailbox_groups: Annotated[
        list[str] | None,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=True)),
    ] = None
    excluded_folders: Annotated[
        list[str] | None, FieldPolicy(FieldClass.SCOPE, scope=ScopeExclude())
    ] = None
    # Adds attachment text to conversation documents.
    include_attachments: Annotated[bool, FieldPolicy(FieldClass.BEHAVIOR)] = False
    include_calendar: Annotated[
        bool, FieldPolicy(FieldClass.SCOPE, scope=ScopeToggle(widens_when=True))
    ] = False
    calendar_past_days: Annotated[int, _CALENDAR_WINDOW] = DEFAULT_CALENDAR_PAST_DAYS
    calendar_future_days: Annotated[int, _CALENDAR_WINDOW] = (
        DEFAULT_CALENDAR_FUTURE_DAYS
    )
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE


def outlook_planning_rule(
    old: OutlookConnectorConfig, new: OutlookConnectorConfig
) -> ConnectorChangeOverride:
    # The window has no effect while the calendar is off on either side:
    # include_calendar carries that change.
    calendar_on = old.include_calendar and new.include_calendar
    mailbox_direction = _mailbox_direction(old, new)
    mailbox_fields = {
        field_name: mailbox_direction
        for field_name, old_value, new_value in (
            (_MAILBOXES, old.mailboxes, new.mailboxes),
            (_MAILBOX_GROUPS, old.mailbox_groups, new.mailbox_groups),
        )
        if old_value != new_value
    }
    return ConnectorChangeOverride(
        scope_directions=mailbox_fields
        | {
            _CALENDAR_PAST_DAYS: _window_direction(
                old.calendar_past_days, new.calendar_past_days, calendar_on
            ),
            _CALENDAR_FUTURE_DAYS: _window_direction(
                old.calendar_future_days, new.calendar_future_days, calendar_on
            ),
        }
    )
