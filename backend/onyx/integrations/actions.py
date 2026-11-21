from collections.abc import Collection

from sqlalchemy.orm import Session

from onyx.db.enums import IntegrationKind
from onyx.db.integration import (
    count_integration_actions,
    list_integration_actions_by_id,
    list_integrations_by_ids,
)
from onyx.db.models import IntegrationAction
from onyx.integrations.kinds.api import api_integration_actions


def integration_actions_by_id(
    integration_ids: Collection[int], db_session: Session
) -> dict[int, list[IntegrationAction]]:
    """Return stored actions. Derive missing API actions from the settings."""
    actions = list_integration_actions_by_id(integration_ids, db_session)
    empty = [integration_id for integration_id, stored in actions.items() if not stored]
    for integration in list_integrations_by_ids(empty, db_session):
        if integration.kind is IntegrationKind.API:
            actions[integration.id] = api_integration_actions(
                integration.id, db_session
            )
    return actions


def integration_actions(
    integration_id: int, db_session: Session
) -> list[IntegrationAction]:
    return integration_actions_by_id([integration_id], db_session)[integration_id]


def count_actions(
    integration_ids: Collection[int], db_session: Session
) -> dict[int, int]:
    counts = count_integration_actions(integration_ids, db_session)
    empty = [integration_id for integration_id, count in counts.items() if not count]
    for integration_id, actions in integration_actions_by_id(empty, db_session).items():
        counts[integration_id] = len(actions)
    return counts
