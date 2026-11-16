"""The action sync: write the actions that a kind finds to
``integration_action``."""

from sqlalchemy.orm import Session

from onyx.db.integration import (
    get_integration_by_id,
    list_integration_actions,
    list_integrations,
    replace_integration_actions__no_commit,
)
from onyx.db.models import Integration
from onyx.error_handling.exceptions import OnyxError
from onyx.integrations.registry import get_kind_handler
from onyx.utils.logger import setup_logger

logger = setup_logger()


def sync_integration_actions__no_commit(
    integration: Integration, db_session: Session
) -> None:
    """Make the ``integration_action`` rows of the integration match what its
    kind finds. The kind is the only writer of the rows, so a stored source
    that the kind no longer finds loses its rows too."""
    handler = get_kind_handler(integration.kind)
    specs = handler.discover_actions(integration, db_session)
    stored_sources = {
        action.source for action in list_integration_actions(integration.id, db_session)
    }
    for source in sorted(stored_sources | {spec.source for spec in specs}):
        replace_integration_actions__no_commit(
            integration.id,
            source,
            [spec for spec in specs if spec.source == source],
            db_session,
        )


def sync_actions_for_integration_id__no_commit(
    integration_id: int | None, db_session: Session
) -> None:
    """Sync the integration of a kind row. Does nothing when the row has no
    integration yet: a row that an old route made gets one later (U6)."""
    if integration_id is None:
        return
    integration = get_integration_by_id(integration_id, db_session)
    if integration is None:
        return
    sync_integration_actions__no_commit(integration, db_session)


def sync_all_integration_actions__no_commit(db_session: Session) -> None:
    """Sync each integration, in id order. An integration with settings that
    do not parse is logged and skipped."""
    for integration in list_integrations(db_session):
        try:
            sync_integration_actions__no_commit(integration, db_session)
        except OnyxError:
            logger.exception(
                "Could not sync the actions of integration %s", integration.id
            )
