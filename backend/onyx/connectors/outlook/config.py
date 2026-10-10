from typing import Annotated

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeDirection,
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
# Directions come from outlook_planning_rule: a larger window widens.
_CALENDAR_WINDOW = FieldPolicy(FieldClass.SCOPE, scope=ScopeOpaque())
_THREAD_ROSTER = FieldPolicy(FieldClass.IDENTITY)


def _window_direction(
    old_days: int, new_days: int, calendar_on: bool
) -> ScopeDirection:
    if old_days == new_days or not calendar_on:
        return ScopeDirection.NONE
    return ScopeDirection.WIDEN if new_days > old_days else ScopeDirection.NARROW


class OutlookConnectorConfig(MicrosoftCloudBinding, ConnectorConfig):
    # The walked mailboxes and folders decide each thread document's builder,
    # content and readers (threads.py), so a change rebuilds every thread.
    mailboxes: Annotated[list[str] | None, _THREAD_ROSTER] = None
    # Entra groups whose members' mailboxes are walked, with the mailboxes
    # above.
    mailbox_groups: Annotated[list[str] | None, _THREAD_ROSTER] = None
    excluded_folders: Annotated[list[str] | None, _THREAD_ROSTER] = None
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
    calendar_on: bool = old.include_calendar and new.include_calendar
    return ConnectorChangeOverride(
        scope_directions={
            _CALENDAR_PAST_DAYS: _window_direction(
                old.calendar_past_days, new.calendar_past_days, calendar_on
            ),
            _CALENDAR_FUTURE_DAYS: _window_direction(
                old.calendar_future_days, new.calendar_future_days, calendar_on
            ),
        }
    )
