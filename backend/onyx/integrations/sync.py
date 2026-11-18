from sqlalchemy.orm import Session

from onyx.db.integration import (
    list_integration_actions,
    lock_integration__no_commit,
    replace_integration_actions__no_commit,
)
from onyx.db.models import Integration
from onyx.integrations.kinds.api import ApiKindHandler


def sync_integration_actions__no_commit(
    integration: Integration, db_session: Session
) -> None:
    """For an API integration only. A stored source that the kind no longer
    finds loses its rows. The kind settings are read under the integration
    lock, so a sync that started earlier cannot write an older action list
    over a newer one."""
    lock_integration__no_commit(integration.id, db_session)
    specs = ApiKindHandler().discover_actions(integration, db_session)
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
