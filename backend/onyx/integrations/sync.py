from sqlalchemy.orm import Session

from onyx.db.integration import (
    list_integration_actions,
    replace_integration_actions__no_commit,
)
from onyx.db.models import Integration
from onyx.integrations.registry import get_kind_handler


def sync_integration_actions__no_commit(
    integration: Integration, db_session: Session
) -> None:
    """A stored source that the kind no longer finds loses its rows."""
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
