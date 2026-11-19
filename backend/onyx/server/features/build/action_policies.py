"""The Craft policy catalog: the integrations that are on for the user."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.integrations.craft import list_task_integration_views
from onyx.server.features.build.models import TaskIntegrationView

router = APIRouter(prefix="/action-policies")


@router.get("")
def list_personal_action_policies(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[TaskIntegrationView]:
    """A new task starts from this catalog."""
    return list_task_integration_views(db_session, user, None)
